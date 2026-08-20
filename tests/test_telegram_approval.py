import json
import unittest
from unittest.mock import patch

import telegram_approval


class TelegramApprovalTests(unittest.TestCase):
    @patch("telegram_approval.set_publication_approval_message_id")
    @patch("telegram_approval.set_publication_approval_expected_chat_id")
    @patch("telegram_approval._api", return_value={"message_id": 91, "chat": {"id": 88}})
    @patch(
        "telegram_approval.create_publication_approval_batch",
        return_value={
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "item_count": 2,
            "status": "PENDING",
        },
    )
    def test_sends_one_expiring_batch_with_approve_and_hold_buttons(
        self, create_batch, api, save_expected_chat_id, save_message_id
    ):
        result = telegram_approval.send_publication_approval(
            [
                {"product_name": "테스트 상품 A", "display_price": 9900},
                {"product_name": "테스트 상품 B", "display_price": 12900},
            ]
        )

        self.assertEqual(result["telegram_message_id"], 91)
        create_batch.assert_called_once()
        save_expected_chat_id.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000", "88")
        save_message_id.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000", 91)
        self.assertEqual(api.call_args.args[0], "sendMessage")
        payload = api.call_args.args[1]
        keyboard = json.loads(payload["reply_markup"])
        self.assertEqual(
            keyboard["inline_keyboard"][0][0]["callback_data"],
            "pa:550e8400-e29b-41d4-a716-446655440000:A",
        )
        self.assertEqual(
            keyboard["inline_keyboard"][0][1]["callback_data"],
            "pa:550e8400-e29b-41d4-a716-446655440000:H",
        )

    @patch("telegram_approval._disable_buttons")
    @patch("telegram_approval._answer_callback")
    @patch(
        "telegram_approval.resolve_publication_approval",
        return_value={"accepted": True, "item_count": 3},
    )
    def test_accepts_approval_callback_once_and_disables_buttons(
        self, resolve, answer, disable
    ):
        telegram_approval.handle_update(
            {
                "callback_query": {
                    "id": "callback-1",
                    "data": "pa:550e8400-e29b-41d4-a716-446655440000:A",
                    "from": {"id": 77},
                    "message": {"message_id": 91, "chat": {"id": 88}},
                }
            }
        )

        resolve.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000", "APPROVED", "88", "77")
        answer.assert_called_once_with("callback-1", "3건 발행 배치를 승인했습니다.")
        disable.assert_called_once_with("88", 91)

    @patch("telegram_approval.set_telegram_approval_chat_candidate")
    def test_records_new_bot_membership_as_approval_channel_candidate(self, set_candidate):
        telegram_approval.handle_update(
            {
                "my_chat_member": {
                    "chat": {"id": -1001234567890},
                    "new_chat_member": {"status": "administrator"},
                }
            }
        )

        set_candidate.assert_called_once_with("-1001234567890")

    @patch("telegram_approval._answer_callback")
    @patch(
        "telegram_approval.resolve_publication_approval",
        return_value={"accepted": False, "reason": "unexpected_chat"},
    )
    def test_rejects_callback_from_unexpected_chat(self, resolve, answer):
        telegram_approval.handle_update(
            {
                "callback_query": {
                    "id": "callback-2",
                    "data": "pa:550e8400-e29b-41d4-a716-446655440000:A",
                    "from": {"id": 99},
                    "message": {"message_id": 91, "chat": {"id": 66}},
                }
            }
        )

        resolve.assert_called_once()
        answer.assert_called_once_with("callback-2", "허용된 채팅에서만 승인할 수 있습니다.")


if __name__ == "__main__":
    unittest.main()


class TelegramMobileControlTests(unittest.TestCase):
    @patch("telegram_approval.active_telegram_approval_chat_id", return_value="88")
    @patch("telegram_approval._api")
    def test_sends_mobile_control_panel(self, api, active_chat):
        telegram_approval.send_mobile_control_panel()

        self.assertEqual(api.call_args.args[0], "sendMessage")
        payload = api.call_args.args[1]
        keyboard = json.loads(payload["reply_markup"])
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "mc:status")
        self.assertEqual(keyboard["inline_keyboard"][1][0]["callback_data"], "mc:pause")
        self.assertEqual(keyboard["inline_keyboard"][1][1]["callback_data"], "mc:resume")

    @patch("telegram_approval.active_telegram_approval_chat_id", return_value="88")
    @patch("telegram_approval._api")
    @patch("telegram_approval._answer_callback")
    @patch("telegram_approval.set_mobile_toss_release_paused")
    def test_pause_callback_sets_release_hold(self, set_paused, answer, api, active_chat):
        telegram_approval.handle_update(
            {
                "callback_query": {
                    "id": "control-1",
                    "data": "mc:pause",
                    "from": {"id": 77},
                    "message": {"message_id": 91, "chat": {"id": 88}},
                }
            }
        )

        set_paused.assert_called_once_with(True)
        answer.assert_called_once_with("control-1", "자동 발행을 보류했습니다.")
        self.assertEqual(api.call_args.args[0], "sendMessage")

    @patch("telegram_approval.active_telegram_approval_chat_id", return_value="88")
    @patch("telegram_approval._api")
    @patch("telegram_approval._answer_callback")
    @patch("telegram_approval.set_mobile_toss_release_paused")
    def test_rejects_mobile_control_from_unexpected_chat(self, set_paused, answer, api, active_chat):
        telegram_approval.handle_update(
            {
                "callback_query": {
                    "id": "control-2",
                    "data": "mc:resume",
                    "from": {"id": 77},
                    "message": {"message_id": 91, "chat": {"id": 99}},
                }
            }
        )

        set_paused.assert_not_called()
        api.assert_not_called()
        answer.assert_called_once_with("control-2", "허용된 승인 채널에서만 사용할 수 있습니다.")
