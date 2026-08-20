from __future__ import annotations

from automation_store import _connect, telegram_update_offset


def main() -> None:
    with _connect() as conn:
        batch = conn.execute(
            """
            SELECT status, item_count, created_at, expires_at, decided_at,
                   COALESCE(telegram_message_id, 0) AS telegram_message_id
            FROM publication_approval_batches
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        events = conn.execute(
            "SELECT count(*) AS count FROM publication_approval_events"
        ).fetchone()
        latest_event = conn.execute(
            """
            SELECT action, detail,
                   substring(md5(actor_chat_id) for 8) AS actor_chat_fingerprint
            FROM publication_approval_events
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        expected = conn.execute(
            """
            SELECT substring(md5(expected_chat_id) for 8) AS expected_chat_fingerprint
            FROM publication_approval_batches
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    print(f"TELEGRAM_UPDATE_OFFSET={telegram_update_offset()}")
    if batch:
        print(f"LATEST_BATCH_STATUS={batch['status']}")
        print(f"LATEST_BATCH_ITEM_COUNT={int(batch['item_count'])}")
        print(f"LATEST_BATCH_MESSAGE_BOUND={int(batch['telegram_message_id']) > 0}")
        print(f"LATEST_BATCH_DECIDED={bool(batch['decided_at'])}")
    else:
        print("LATEST_BATCH_STATUS=NONE")
    print(f"APPROVAL_EVENT_COUNT={int((events or {}).get('count') or 0)}")
    if latest_event:
        print(f"LATEST_APPROVAL_EVENT={latest_event['action']}:{latest_event['detail']}")
        print(f"LATEST_EVENT_CHAT_FINGERPRINT={latest_event['actor_chat_fingerprint']}")
    if expected:
        print(f"EXPECTED_CHAT_FINGERPRINT={expected['expected_chat_fingerprint']}")


if __name__ == "__main__":
    main()
