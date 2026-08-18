import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation_store import write_audit_csv


class AuditCsvTests(unittest.TestCase):
    def test_context_secrets_are_redacted_before_csv_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.csv"
            with patch("automation_store.AUTOMATION_AUDIT_CSV_PATH", str(path)):
                write_audit_csv(
                    "run",
                    {
                        "platform": "toss",
                        "status": "FAILED",
                        "context": {
                            "token": "should-never-appear",
                            "nested": {"password": "also-hidden"},
                            "required_action": "로그인 상태 확인",
                        },
                    },
                )
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("should-never-appear", content)
            self.assertNotIn("also-hidden", content)
            self.assertIn("[REDACTED]", content)
            self.assertIn("로그인 상태 확인", content)


if __name__ == "__main__":
    unittest.main()
