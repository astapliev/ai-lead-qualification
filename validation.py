"""Validate the public form contract before any request reaches n8n."""

import re
import unicodedata
from uuid import UUID


ALLOWED_SERVICES = frozenset({
    "AI-автоматизация продаж",
    "Автоматизация документооборота",
    "AI-бот и поддержка клиентов",
    "Интеграция CRM и бизнес-систем",
    "Другая AI-автоматизация",
})

ALLOWED_TIMELINES = frozenset({
    "Срочно — до 7 дней",
    "1–2 недели",
    "До 1 месяца",
    "1–3 месяца",
    "Сроки гибкие",
})

_TELEGRAM = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,31}\Z")
_PHONE = re.compile(r"\+7[0-9]{10}\Z")
_EMAIL_LOCAL = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*\Z"
)
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_EMAIL_TLD = re.compile(r"[A-Za-z]{2,63}\Z")


def normalize_contact(contact):
    """Accept only a recognized contact type and its complete canonical value."""
    if not isinstance(contact, str):
        return None

    contact_type, separator, value = contact.partition(":")
    if not separator:
        return None
    value = value.strip()

    if contact_type == "Telegram" and _TELEGRAM.fullmatch(value):
        return f"Telegram: {value.lower()}"

    if contact_type == "Телефон" and _PHONE.fullmatch(value):
        return f"Телефон: {value}"

    if contact_type == "Email" and len(value) <= 254 and value.count("@") == 1:
        local, domain = value.split("@")
        labels = domain.split(".")
        if (
            1 <= len(local) <= 64
            and _EMAIL_LOCAL.fullmatch(local)
            and len(labels) >= 2
            and all(_DOMAIN_LABEL.fullmatch(label) for label in labels)
            and _EMAIL_TLD.fullmatch(labels[-1])
        ):
            return f"Email: {value.lower()}"

    return None


def validate_lead(payload):
    """Return the seven normalized n8n fields and field-specific errors.

    This checks structure and format, not whether a contact exists or whether
    the description is truthful. Extra client keys are never forwarded.
    """
    errors = {}

    name = payload.get("name")
    if isinstance(name, str):
        name = " ".join(name.split())
        valid_characters = all(
            unicodedata.category(character)[0] in {"L", "M"}
            or character in " -'’"
            for character in name
        )
        letter_count = sum(
            unicodedata.category(character).startswith("L") for character in name
        )
        if not (2 <= len(name) <= 60 and valid_characters and letter_count >= 2):
            errors["name"] = "Укажите имя: от 2 до 60 символов, буквы, пробелы, дефис или апостроф."
    else:
        errors["name"] = "Укажите имя."

    service = payload.get("service")
    if not isinstance(service, str) or service not in ALLOWED_SERVICES:
        errors["service"] = "Выберите вариант из списка, включая «Другая задача / пока не знаю»."

    contact = normalize_contact(payload.get("contact"))
    if contact is None:
        errors["contact"] = "Укажите корректный Telegram, email или российский телефон."

    budget = payload.get("budget")
    if budget is not None and (type(budget) is not int or not 1 <= budget <= 1_000_000_000):
        errors["budget"] = "Укажите целую сумму от 1 до 1 000 000 000 ₽ или оставьте бюджет неизвестным."

    timeline = payload.get("timeline")
    if timeline is None or timeline == "":
        timeline = None
    elif not isinstance(timeline, str) or timeline not in ALLOWED_TIMELINES:
        errors["timeline"] = "Выберите срок из списка."

    message = payload.get("message")
    if isinstance(message, str):
        message = message.strip()
        if "\x00" in message or not 20 <= len(message) <= 2000:
            errors["message"] = "Опишите задачу: от 20 до 2000 символов."
    else:
        errors["message"] = "Опишите задачу."

    request_id = payload.get("request_id")
    try:
        parsed_id = UUID(request_id) if isinstance(request_id, str) else None
    except (ValueError, AttributeError):
        parsed_id = None
    if parsed_id is None or parsed_id.version != 4 or str(parsed_id) != request_id:
        errors["request_id"] = "Некорректный идентификатор заявки. Обновите страницу."

    if errors:
        return None, errors

    return {
        "request_id": request_id,
        "name": name,
        "contact": contact,
        "service": service,
        "budget": budget,
        "message": message,
        "timeline": timeline,
    }, {}
