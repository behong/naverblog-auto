import unittest
from datetime import datetime, timezone
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

    def test_operations_text_hides_credentials_and_non_public_links(self) -> None:
        result = automation_store._operations_safe_text(
            "api key=not-for-dashboard 연결 실패 https://example.invalid/private"
        )
        self.assertIn("api key=[숨김]", result)
        self.assertIn("[링크 숨김]", result)
        self.assertNotIn("not-for-dashboard", result)
        self.assertNotIn("example.invalid", result)

    def test_operations_public_url_accepts_only_naver_post(self) -> None:
        self.assertEqual(
            automation_store._operations_public_post_url("https://blog.naver.com/sijm/224385521856"),
            "https://blog.naver.com/sijm/224385521856",
        )
        self.assertEqual(automation_store._operations_public_post_url("https://toss.im/_m/example"), "")
        self.assertEqual(automation_store._operations_public_post_url("javascript:alert(1)"), "")

    def test_toss_operations_summary_is_read_only_and_safe(self) -> None:
        now = datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)
        query_log = []
        responses = [
            [{
                "sequence_no": 1,
                "product_id": "item-1",
                "product_name": "테스트 상품",
                "expected_price": 8900,
                "status": "PUBLISHED",
                "created_at": now,
                "released_at": now,
                "finished_at": now,
                "error_message": "",
                "naver_post_url": "https://blog.naver.com/sijm/224385521856",
            }],
            [{
                "product_name": "테스트 상품",
                "naver_post_url": "https://blog.naver.com/sijm/224385521856",
                "published_at": now,
            }],
            [{
                "product_name": "오류 상품",
                "status": "FAILED",
                "step": "publish",
                "error_message": "api key=not-for-dashboard https://example.invalid/private",
                "retry_count": 1,
                "updated_at": now,
            }],
        ]

        class Result:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self):
                self.position = 0

            def execute(self, query, *_args):
                query_log.append(query)
                result = Result(responses[self.position])
                self.position += 1
                return result

        class ConnectionContext:
            def __init__(self):
                self.connection = Connection()

            def __enter__(self):
                return self.connection

            def __exit__(self, *_args):
                return False

        with (
            patch.object(automation_store, "korea_today", return_value=now.date()),
            patch.object(
                automation_store,
                "mobile_toss_status",
                return_value={
                    "release_paused": False,
                    "auto_publish_enabled": True,
                    "queue": {"QUEUED": 0, "RELEASED": 0, "PUBLISHED": 1, "FAILED_PRE_SUBMIT": 0, "PUBLISH_UNKNOWN": 0, "SKIPPED": 0},
                    "windows": [{"source": "toss-draft-window:morning", "status": "APPROVED", "item_count": 4}],
                },
            ),
            patch.object(automation_store, "_connect", return_value=ConnectionContext()),
        ):
            result = automation_store.toss_operations_summary()

        self.assertEqual(result["queue"][0]["public_url"], "https://blog.naver.com/sijm/224385521856")
        self.assertEqual(result["recent_published"][0]["public_url"], "https://blog.naver.com/sijm/224385521856")
        self.assertIn("api key=[숨김]", result["recent_errors"][0]["error_message"])
        self.assertIn("[링크 숨김]", result["recent_errors"][0]["error_message"])
        self.assertTrue(all("SELECT" in query.upper() for query in query_log))


if __name__ == "__main__":
    unittest.main()
