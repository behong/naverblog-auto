"""Hold all pending Toss preflight approvals without exposing batch or credential data."""

from automation_store import _connect


def main() -> None:
    with _connect() as conn:
        held_rows = conn.execute(
            """
            UPDATE publication_approval_batches
            SET status = 'HELD',
                decided_at = now(),
                decided_by_user_id = 'system-recovery'
            WHERE status = 'PENDING'
              AND source = 'toss-preflight'
            RETURNING id
            """
        ).fetchall()
        for row in held_rows:
            conn.execute(
                """
                INSERT INTO publication_approval_events
                    (batch_id, action, actor_user_id, actor_chat_id, detail)
                VALUES (%s, 'HELD', 'system-recovery', '', 'operator_hold')
                """,
                (row["id"],),
            )
    print(f"HELD_PENDING_TOSS_PREFLIGHT_COUNT={len(held_rows)}")


if __name__ == "__main__":
    main()
