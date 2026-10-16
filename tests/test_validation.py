import unittest

from validation import validate_lead


def example_lead(**changes):
    payload = {
        "request_id": "bbfb5164-a688-4cac-95f3-9ccc0476bfa9",
        "name": "Ацамаз",
        "contact": "Telegram: @Example_User",
        "service": "Интеграция CRM и бизнес-систем",
        "budget": 150000,
        "message": "Перенести заявки из формы в CRM и уведомлять команду.",
        "timeline": None,
    }
    payload.update(changes)
    return payload


class LeadValidationTests(unittest.TestCase):
    def test_normalization_preserves_description_lines_and_drops_extra_keys(self):
        normalized, errors = validate_lead(example_lead(
            name="  Ацамаз   Плиев  ",
            message="  Перенести заявки из формы в CRM.\n\nСохранить историю.  ",
            timeline="",
            admin=True,
        ))
        self.assertEqual(errors, {})
        self.assertEqual(normalized["name"], "Ацамаз Плиев")
        self.assertEqual(normalized["contact"], "Telegram: @example_user")
        self.assertEqual(normalized["message"], "Перенести заявки из формы в CRM.\n\nСохранить историю.")
        self.assertIsNone(normalized["timeline"])
        self.assertEqual(set(normalized), {
            "request_id", "name", "contact", "service", "budget", "message", "timeline",
        })

    def test_fake_selected_values_are_rejected(self):
        normalized, errors = validate_lead(example_lead(service="<script>", timeline="завтра"))
        self.assertIsNone(normalized)
        self.assertEqual(set(errors), {"service", "timeline"})

    def test_budget_requires_a_json_integer_within_bounds(self):
        for value in (True, False, "150000", 150000.0, 0, -1, 1_000_000_001, [], {}):
            with self.subTest(value=value):
                normalized, errors = validate_lead(example_lead(budget=value))
                self.assertIsNone(normalized)
                self.assertIn("budget", errors)
        for value in (1, 1_000_000_000):
            with self.subTest(value=value):
                self.assertEqual(validate_lead(example_lead(budget=value))[1], {})

    def test_unknown_budget_is_null_not_zero(self):
        normalized, errors = validate_lead(example_lead(budget=None))
        self.assertEqual(errors, {})
        self.assertIsNone(normalized["budget"])
        missing = example_lead()
        missing.pop("budget")
        self.assertIsNone(validate_lead(missing)[0]["budget"])
        self.assertIn("budget", validate_lead(example_lead(budget=0))[1])

    def test_uuid_requires_canonical_v4(self):
        for value in (
            None,
            42,
            "bbfb5164a6884cac95f39ccc0476bfa9",
            "{bbfb5164-a688-4cac-95f3-9ccc0476bfa9}",
            "bbfb5164-a688-1cac-95f3-9ccc0476bfa9",
            "not-a-uuid",
        ):
            with self.subTest(value=value):
                self.assertIn("request_id", validate_lead(example_lead(request_id=value))[1])

    def test_unicode_names_accept_real_scripts_and_reject_markup(self):
        for name in ("李明", "Ацамаз Плиев", "Anne-Marie", "O’Connor", "Jose\u0301"):
            with self.subTest(name=name):
                self.assertEqual(validate_lead(example_lead(name=name))[1], {})
        for name in ("", "A", "--", "\u0301\u0301", "Имя123", "<Иван>", "А\u200bцамаз", "А" * 61):
            with self.subTest(name=name):
                self.assertIn("name", validate_lead(example_lead(name=name))[1])

    def test_message_limits_use_codepoints_and_do_not_guess_meaning(self):
        for message in ("A" * 20, "👋" * 20, "А" * 2000):
            with self.subTest(length=len(message)):
                self.assertEqual(validate_lead(example_lead(message=message))[1], {})
        for message in (None, [], " " * 30, "А" * 19, "А" * 2001):
            with self.subTest(message_type=type(message).__name__):
                self.assertIn("message", validate_lead(example_lead(message=message))[1])

    def test_contacts_accept_canonical_values(self):
        cases = {
            "Telegram: @Valid_User": "Telegram: @valid_user",
            "Email: PERSON+crm@Sub.Example.COM": "Email: person+crm@sub.example.com",
            "Телефон: +79991234567": "Телефон: +79991234567",
        }
        for contact, expected in cases.items():
            with self.subTest(contact=contact):
                normalized, errors = validate_lead(example_lead(contact=contact))
                self.assertEqual(errors, {})
                self.assertEqual(normalized["contact"], expected)

    def test_contacts_reject_truncation_and_invalid_addresses(self):
        for contact in (
            None,
            "@valid_user",
            "WhatsApp: +79991234567",
            "Telegram: https://t.me/valid_user",
            "Telegram: @valid_user/extra",
            "Telegram: @valid_user?text=hello",
            "Telegram: @tiny",
            "Email: a..b@example.com",
            "Email: .a@example.com",
            "Email: a.@example.com",
            "Email: a@under_score.example.com",
            "Email: a@-example.com",
            "Email: a@example.c",
            "Email: a@example.12",
            "Email: " + "a" * 65 + "@example.com",
            "Email: имя@example.com",
            "Телефон: 89991234567",
            "Телефон: +7+9991234567",
            "Телефон: +7 999 123-45-67",
            "Телефон: +7999123456",
        ):
            with self.subTest(contact=contact):
                self.assertIn("contact", validate_lead(example_lead(contact=contact))[1])

    def test_all_wrong_json_field_types_return_errors_without_crashing(self):
        normalized, errors = validate_lead({
            "request_id": {}, "name": [], "contact": {}, "service": [],
            "budget": {}, "message": {}, "timeline": [],
        })
        self.assertIsNone(normalized)
        self.assertEqual(set(errors), {
            "request_id", "name", "contact", "service", "budget", "message", "timeline",
        })


if __name__ == "__main__":
    unittest.main()
