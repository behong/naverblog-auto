from __future__ import annotations

import argparse

from automation_store import _connect


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Toss draft-window batch to queue bindings.")
    parser.add_argument("--window-key", required=True)
    args = parser.parse_args()
    source_prefix = f"toss-draft-window:{str(args.window_key).strip().lower()}"

    with _connect() as conn:
        batches = conn.execute(
            """
            SELECT id, source, status, publish_state, item_count, created_at,
                   created_at::date AS database_date,
                   (created_at AT TIME ZONE 'Asia/Seoul')::date AS korea_date
            FROM publication_approval_batches
            WHERE source LIKE %s
            ORDER BY created_at DESC
            """,
            (f"{source_prefix}%",),
        ).fetchall()
        for batch in batches:
            queue_rows = conn.execute(
                """
                SELECT schedule_date, status, COUNT(*) AS item_count
                FROM scheduled_toss_publish_items
                WHERE master_batch_id = %s
                GROUP BY schedule_date, status
                ORDER BY schedule_date, status
                """,
                (batch["id"],),
            ).fetchall()
            print(
                "BATCH|{id}|{source}|{status}|{publish_state}|{item_count}|{database_date}|{korea_date}".format(
                    id=batch["id"],
                    source=batch["source"],
                    status=batch["status"],
                    publish_state=batch["publish_state"],
                    item_count=batch["item_count"],
                    database_date=batch["database_date"],
                    korea_date=batch["korea_date"],
                )
            )
            for queue in queue_rows:
                print(f"QUEUE|{batch['id']}|{queue['schedule_date']}|{queue['status']}|{queue['item_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
