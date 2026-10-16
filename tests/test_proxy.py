import importlib
import os
import unittest
from unittest.mock import Mock, patch

import requests

from test_validation import example_lead


def public_lead(**changes):
    payload = {**example_lead(), "consent": True, "website": ""}
    payload.update(changes)
    return payload


# Tests use dummy settings and never read a real .env or reach a real webhook.
with patch.dict(os.environ, {
    "N8N_WEBHOOK_URL": "https://example.invalid/webhook/test",
    "N8N_WEBHOOK_SECRET": "test-only-placeholder",
}), patch("dotenv.load_dotenv"):
    proxy = importlib.import_module("app")


class LeadProxyTests(unittest.TestCase):
    def setUp(self):
        proxy.app.config["TESTING"] = True
        self.client = proxy.app.test_client()
        self.outbound = patch("app.get_session")
        self.post = self.outbound.start().return_value.post
        self.addCleanup(self.outbound.stop)
        upstream = Mock(ok=True, status_code=202)
        upstream.json.return_value = {"success": True, "status": "accepted", "duplicate": False, "request_id": example_lead()["request_id"]}
        self.post.return_value = upstream

    def test_unknown_budget_forwarded_as_null_with_only_seven_fields(self):
        response = self.client.post("/api/lead", json=public_lead(budget=None))
        self.assertEqual(response.status_code, 202)
        forwarded = self.post.call_args.kwargs["json"]
        self.assertIsNone(forwarded["budget"])
        self.assertNotIn("consent", forwarded)
        self.assertNotIn("website", forwarded)
        self.assertEqual(len(forwarded), 7)

    def test_consent_checked_after_form_data(self):
        response = self.client.post("/api/lead", json=public_lead(name="", consent=False))
        self.assertIn("name", response.json["field_errors"])
        self.assertNotIn("consent", response.json["field_errors"])
        for value in (False, None, "true", 1):
            with self.subTest(value=value):
                response = self.client.post("/api/lead", json=public_lead(consent=value))
                self.assertEqual(response.status_code, 400)
                self.assertIn("consent", response.json["field_errors"])
        self.post.assert_not_called()

    def test_honeypot_checked_on_server(self):
        for value in ("bot-filled", True, {}, []):
            with self.subTest(value=value):
                response = self.client.post("/api/lead", json=public_lead(website=value))
                self.assertEqual(response.status_code, 400)
                self.assertIs(response.json["success"], False)
        self.post.assert_not_called()

    def test_invalid_fields_never_reach_n8n(self):
        response = self.client.post("/api/lead", json=public_lead(
            budget=True,
            timeline="tampered-value",
            contact="Email: a..b@example.com",
        ))
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIs(data["success"], False)
        self.assertEqual(set(data["field_errors"]), {"budget", "timeline", "contact"})
        self.assertEqual(len(data["errors"]), 3)
        self.post.assert_not_called()

    def test_invalid_json_never_reaches_n8n(self):
        for body in ("not-json", "[]", "null"):
            with self.subTest(body=body):
                response = self.client.post("/api/lead", data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertIs(response.get_json()["success"], False)
        self.post.assert_not_called()

    def test_large_request_returns_json_413_without_reaching_n8n(self):
        response = self.client.post("/api/lead", data="x" * (32 * 1024 + 1), content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertIs(response.get_json()["success"], False)
        self.post.assert_not_called()
        with self.client.get("/") as page_response:
            self.assertEqual(page_response.status_code, 200)

    def test_only_normalized_contract_fields_are_forwarded(self):
        response = self.client.post("/api/lead", json=public_lead(
            name="  Ацамаз   Плиев  ",
            message="  Перенести заявки в CRM.\nСохранить историю.  ",
            secret="client-extra-key",
        ))
        self.assertEqual(response.status_code, 202)
        forwarded = self.post.call_args.kwargs["json"]
        self.assertEqual(forwarded["name"], "Ацамаз Плиев")
        self.assertEqual(forwarded["contact"], "Telegram: @example_user")
        self.assertEqual(forwarded["message"], "Перенести заявки в CRM.\nСохранить историю.")
        self.assertNotIn("secret", forwarded)
        self.assertEqual(len(forwarded), 7)

    def test_retry_forwards_same_request_id(self):
        payload = public_lead()
        self.post.side_effect = [requests.Timeout(), self.post.return_value]
        self.assertEqual(self.client.post("/api/lead", json=payload).status_code, 504)
        self.assertEqual(self.client.post("/api/lead", json=payload).status_code, 202)
        self.assertEqual(
            self.post.call_args_list[0].kwargs["json"]["request_id"],
            self.post.call_args_list[1].kwargs["json"]["request_id"],
        )

    def test_malformed_upstream_response_returns_502(self):
        upstream = self.post.return_value
        for value in (None, [], {"success": "true"}, {"result": "ok"}):
            with self.subTest(value=value):
                upstream.json.return_value = value
                response = self.client.post("/api/lead", json=public_lead())
                self.assertEqual(response.status_code, 502)
                self.assertIs(response.get_json()["success"], False)
        upstream.json.side_effect = ValueError("invalid json")
        self.assertEqual(self.client.post("/api/lead", json=public_lead()).status_code, 502)

    def test_upstream_failure_cannot_be_reported_as_success(self):
        self.post.return_value.json.return_value = {"success": False, "message": "Processing failed"}
        response = self.client.post("/api/lead", json=public_lead())
        self.assertEqual(response.status_code, 502)
        self.assertIs(response.get_json()["success"], False)

    def test_connection_failure_and_duplicate_response_keep_contract(self):
        self.post.side_effect = requests.ConnectionError()
        self.assertEqual(self.client.post("/api/lead", json=public_lead()).status_code, 502)
        self.post.side_effect = None
        self.post.return_value.json.return_value = {"success": True, "status": "accepted", "duplicate": True, "request_id": example_lead()["request_id"]}
        response = self.client.post("/api/lead", json=public_lead())
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json["duplicate"])
        self.assertEqual(response.json["request_id"], example_lead()["request_id"])


    def test_success_requires_matching_durable_acceptance_contract(self):
        good = dict(self.post.return_value.json.return_value)
        for change in ({"request_id": "wrong"}, {"duplicate": "false"}, {"status": "started"}):
            self.post.return_value.json.return_value = {**good, **change}
            self.assertEqual(self.client.post("/api/lead", json=public_lead()).status_code, 502)
        self.post.return_value.json.return_value = good
        self.post.return_value.status_code = 200
        self.assertEqual(self.client.post("/api/lead", json=public_lead()).status_code, 502)

    def test_internal_error_and_secret_never_forwarded(self):
        self.post.return_value.status_code = 503
        self.post.return_value.json.return_value = {"success": False, "message": "PRIVATE_TOKEN"}
        response = self.client.post("/api/lead", json=public_lead())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("PRIVATE_TOKEN", response.get_data(as_text=True))
        self.assertIn("flask;dur=", response.headers["Server-Timing"])

    def test_nul_rejected_before_transport(self):
        response = self.client.post("/api/lead", json=public_lead(message="Текст задачи достаточно длинный\x00"))
        self.assertEqual(response.status_code, 400)
        self.post.assert_not_called()

    def test_redirects_disabled_and_conflict_preserved(self):
        self.post.return_value.status_code = 409
        self.post.return_value.json.return_value = {"success": False}
        response = self.client.post("/api/lead", json=public_lead())
        self.assertEqual(response.status_code, 409)
        self.assertIs(self.post.call_args.kwargs["allow_redirects"], False)


if __name__ == "__main__":
    unittest.main()
