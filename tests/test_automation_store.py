import unittest
from unittest.mock import patch

import automation_store


class AutomationStoreTests(unittest.TestCase):
    def test_authorized_uses_bearer_token(self) -> None:
        with patch.object(automation_store, "AUTOMATION_API_TOKEN", "test-secret"):
            self.assertTrue(automation_store.authorized("Bearer test-secret"))
            self.assertFalse(automation_store.authorized("Bearer wrong"))
            self.assertFalse(automation_store.authorized(None))

    def test_platform_validation(self) -> None:
        self.assertEqual(automation_store._platform({"platform": "Coupang"}), "coupang")
        self.assertEqual(automation_store._platform({"platform": "Threads"}), "threads")
        with self.assertRaisesRegex(ValueError, "platform"):
            automation_store._platform({"platform": "unknown"})

    def test_optional_price_accepts_commas(self) -> None:
        self.assertEqual(
            automation_store._optional_price({"sale_price": "14,900"}, "sale_price"),
            14900,
        )

    def test_notify_is_disabled_without_secrets(self) -> None:
        with (
            patch.object(automation_store, "TELEGRAM_BOT_TOKEN", ""),
            patch.object(automation_store, "TELEGRAM_CHAT_ID", ""),
        ):
            self.assertFalse(automation_store.notify_telegram("test"))


if __name__ == "__main__":
    unittest.main()
