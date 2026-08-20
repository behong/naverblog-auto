import unittest
from unittest.mock import MagicMock, patch

import automation_store


class TossPublisherSettingsTests(unittest.TestCase):
    def _database_connection(self, publisher_id: str):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = {
            "toss_publisher_id": publisher_id
        }
        context_manager = MagicMock()
        context_manager.__enter__.return_value = connection
        return context_manager, connection

    def test_environment_value_has_priority_without_database_query(self):
        with patch.object(
            automation_store,
            "TOSS_OPEN_API_PUBLISHER_ID",
            "550e8400-e29b-41d4-a716-446655440000",
        ), patch.object(automation_store, "_connect") as connect:
            self.assertEqual(
                automation_store.admin_toss_publisher_id(),
                "550e8400-e29b-41d4-a716-446655440000",
            )
            self.assertEqual(
                automation_store.admin_toss_publisher_settings(),
                {"configured": True, "source": "environment"},
            )
            connect.assert_not_called()

    def test_database_value_is_used_when_environment_is_empty(self):
        context_manager, connection = self._database_connection(
            "11111111-2222-4333-8444-555555555555"
        )
        with patch.object(automation_store, "TOSS_OPEN_API_PUBLISHER_ID", ""), patch.object(
            automation_store, "_connect", return_value=context_manager
        ):
            self.assertEqual(
                automation_store.admin_toss_publisher_id(),
                "11111111-2222-4333-8444-555555555555",
            )
            self.assertEqual(
                automation_store.admin_toss_publisher_settings(),
                {"configured": True, "source": "database"},
            )
        self.assertEqual(connection.execute.call_count, 2)

    def test_unset_is_reported_when_neither_source_has_a_value(self):
        context_manager, _ = self._database_connection("")
        with patch.object(automation_store, "TOSS_OPEN_API_PUBLISHER_ID", ""), patch.object(
            automation_store, "_connect", return_value=context_manager
        ):
            self.assertEqual(
                automation_store.admin_toss_publisher_settings(),
                {"configured": False, "source": "unset"},
            )


if __name__ == "__main__":
    unittest.main()
