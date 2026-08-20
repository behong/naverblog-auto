from datetime import date
import unittest
from unittest.mock import patch

import automation_store


class MobileReleaseGateTests(unittest.TestCase):
    @patch("automation_store.mobile_toss_release_paused", return_value=True)
    def test_paused_mobile_control_blocks_release_before_database_work(self, paused):
        result = automation_store.release_next_scheduled_toss_item(date(2026, 8, 20))

        self.assertEqual(result, {"released": False, "reason": "mobile_release_paused"})
        paused.assert_called_once()


if __name__ == "__main__":
    unittest.main()
