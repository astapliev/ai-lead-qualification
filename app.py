import os
import threading
import time

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, g
from werkzeug.exceptions import RequestEntityTooLarge

from validation import validate_lead


load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET")

if not N8N_WEBHOOK_URL or not N8N_WEBHOOK_SECRET:
    raise RuntimeError("Не заданы N8N_WEBHOOK_URL или N8N_WEBHOOK_SECRET")


app = Flask(
    __name__,
    static_folder="static",
    static_url_path="",
)

app.config["MAX_CONTENT_LENGTH"] = 32 * 1024


_session_local = threading.local()


def get_session():
    # One reusable HTTP session per serving thread; never share mutable sessions.
    if not hasattr(_session_local, "session"):
        _session_local.session = requests.Session()
    return _session_local.session


@app.before_request
def start_request_timer():
    g.request_started_at = time.perf_counter()


@app.after_request
def add_request_timing(response):
    elapsed = (time.perf_counter() - g.request_started_at) * 1000
    response.headers["Server-Timing"] = f"flask;dur={elapsed:.1f}"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    message = "Заявка слишком большая. Максимальный размер — 32 КБ."

    return jsonify({
        "success": False,
        "message": message,
        "errors": [message],
        "field_errors": {},
    }), 413


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/lead")
def create_lead():

    public_payload = request.get_json(silent=True)

    if not isinstance(public_payload, dict):
        return jsonify({
            "success": False,
            "message": "Ожидался JSON-объект",
            "errors": ["Ожидался JSON-объект"],
            "field_errors": {},
        }), 400

    payload, field_errors = validate_lead(public_payload)

    if field_errors:
        return jsonify({
            "success": False,
            "message": "Проверьте данные заявки.",
            "errors": list(field_errors.values()),
            "field_errors": field_errors,
        }), 400

    website = public_payload.get("website", "")

    if not isinstance(website, str) or website.strip():
        return jsonify({
            "success": False,
            "message": "Не удалось отправить заявку. Обновите страницу и попробуйте снова.",
        }), 400

    if public_payload.get("consent") is not True:
        message = "Для отправки нужно согласие на обработку данных."

        return jsonify({
            "success": False,
            "message": message,
            "errors": [message],
            "field_errors": {"consent": message},
        }), 400

    # Intake must confirm durable storage before returning success.
    started = time.perf_counter()
    try:
        response = get_session().post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={"X-Webhook-Secret": N8N_WEBHOOK_SECRET},
            timeout=(5, 15),
            allow_redirects=False,
        )
    except requests.Timeout:
        return jsonify({
            "success": False,
            "message": "Не удалось получить подтверждение. Повторите отправку с тем же идентификатором заявки.",
        }), 504
    except requests.RequestException:
        return jsonify({
            "success": False,
            "message": "Не удалось связаться с сервисом обработки заявки.",
        }), 502
    finally:
        # Never log the payload, destination URL, secret, or transport exception.
        app.logger.info("lead_intake_duration_ms=%.1f", (time.perf_counter() - started) * 1000)

    try:
        data = response.json()
    except ValueError:
        data = None

    if (not isinstance(data, dict)
            or not isinstance(data.get("success"), bool)
            or response.status_code not in (200, 202, 400, 409, 429, 500, 502, 503, 504)):
        return jsonify({"success": False, "message": "Некорректный ответ сервиса обработки."}), 502

    if response.status_code >= 400:
        if data["success"]:
            return jsonify({"success": False, "message": "Ошибка сервиса обработки."}), 502
        safe = {"success": False, "message": "Не удалось принять заявку. Попробуйте повторить отправку."}
        if response.status_code == 409:
            safe.update(code="request_id_conflict", request_id=payload["request_id"],
                        message="Этот идентификатор уже использован для другой заявки.")
        if response.status_code == 400:
            safe["message"] = "Проверьте данные заявки."
            fields = data.get("field_errors")
            if isinstance(fields, dict):
                safe["field_errors"] = {key: "Проверьте значение поля." for key in payload if key in fields}
                safe["errors"] = list(safe["field_errors"].values())
        return jsonify(safe), response.status_code

    if (response.status_code != 202 or data["success"] is not True
            or data.get("status") != "accepted"
            or type(data.get("duplicate")) is not bool
            or data.get("request_id") != payload["request_id"]):
        return jsonify({"success": False, "message": "Сервис не подтвердил приём заявки."}), 502

    return jsonify({
        "success": True, "status": "accepted", "duplicate": data["duplicate"],
        "request_id": payload["request_id"],
        "message": "Заявка уже принята в обработку" if data["duplicate"] else "Заявка принята в обработку",
    }), 202


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        debug=os.getenv("FLASK_DEBUG") == "1",
    )