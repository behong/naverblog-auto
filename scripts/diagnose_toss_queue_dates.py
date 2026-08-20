from __future__ import annotations

from datetime import timedelta

from automation_store import _connect
from kst_time import korea_today


def main() -> None:
    today = korea_today()
    yesterday = today - timedelta(days=1)
    with _connect() as conn:
        queue_rows = conn.execute(
            """
            SELECT schedule_date, status, COUNT(*) AS item_count
            FROM scheduled_toss_publish_items
            WHERE schedule_date IN (%s, %s)
            GROUP BY schedule_date, status
            ORDER BY schedule_date, status
            """,
            (yesterday, today),
        ).fetchall()
        batch_rows = conn.execute(
            """
            SELECT COALESCE(source, '') AS source, status, publish_state, item_count
            FROM publication_approval_batches
            WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY created_at
            """,
            (today,),
        ).fetchall()

    print(f"TODAY={today.isoformat()}")
    for row in queue_rows:
        print(f"QUEUE|{row['schedule_date']}|{row['status']}|{row['item_count']}")
    if not queue_rows:
        print("QUEUE|NONE")
    for row in batch_rows:
        print(f"BATCH|{row['source']}|{row['status']}|{row['publish_state']}|{row['item_count']}")
    if not batch_rows:
        print("BATCH|NONE")


if __name__ == "__main__":
    main()
