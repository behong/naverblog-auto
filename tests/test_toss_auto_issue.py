import unittest
from unittest.mock import patch

from toss_collector import QUOTA_EXCEEDED_CODE, auto_issue_toss_share_links
from toss_open_api import TossOpenApiError


class TossAutoIssueTests(unittest.TestCase):
    @patch("toss_collector.issue_toss_share_link")
    @patch("toss_collector.admin_toss_publisher_id", return_value="550e8400-e29b-41d4-a716-446655440000")
    @patch("toss_collector.AUTO_ISSUE_SHARE_LINKS", True)
    def test_issues_only_unique_saleable_options_and_reuses_existing_links(
        self, _publisher, issue_link
    ):
        issue_link.side_effect = [
            {"short_url": "https://toss.im/_m/new", "reused": False},
            {"short_url": "https://toss.im/_m/existing", "reused": True},
        ]

        result = auto_issue_toss_share_links(
            [
                {"taca_item_id": "101", "is_sold_out": False},
                {"taca_item_id": "101", "is_sold_out": False},
                {"taca_item_id": "102", "is_sold_out": True},
                {"taca_item_id": "", "is_sold_out": False},
                {"taca_item_id": "103", "is_sold_out": False},
            ]
        )

        self.assertEqual(issue_link.call_count, 2)
        self.assertEqual(result["candidates"], 2)
        self.assertEqual(result["issued"], 1)
        self.assertEqual(result["reused"], 1)
        self.assertEqual(result["skipped_sold_out"], 1)
        self.assertEqual(result["skipped_invalid"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(result["quota_exceeded"])

    @patch("toss_collector.issue_toss_share_link")
    @patch("toss_collector.admin_toss_publisher_id", return_value="550e8400-e29b-41d4-a716-446655440000")
    @patch("toss_collector.AUTO_ISSUE_SHARE_LINKS", True)
    def test_stops_cleanly_when_daily_quota_is_exhausted(
        self, _publisher, issue_link
    ):
        issue_link.side_effect = TossOpenApiError(
            "daily quota reached", code=QUOTA_EXCEEDED_CODE
        )

        result = auto_issue_toss_share_links(
            [
                {"taca_item_id": "201", "is_sold_out": False},
                {"taca_item_id": "202", "is_sold_out": False},
            ]
        )

        issue_link.assert_called_once_with("201")
        self.assertTrue(result["quota_exceeded"])
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["issued"], 0)
        self.assertEqual(result["reused"], 0)


if __name__ == "__main__":
    unittest.main()
