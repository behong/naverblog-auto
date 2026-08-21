from __future__ import annotations

import json
from datetime import date

from automation_store import _connect


def main() -> None:
    today = date.today()
    with _connect() as conn:
        batch = conn.execute(
            """
            SELECT id, publish_state, created_at
            FROM publication_approval_batches
            WHERE source = 'toss-draft-window:midday'
              AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (today,),
        ).fetchone()
        queue_count = 0
        if batch:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM scheduled_toss_publish_items
                WHERE schedule_date = %s
                  AND master_batch_id = %s
                """,
                (today, str(batch['id'])),
            ).fetchone()
            queue_count = int(row['count']) if row else 0

    print(
        json.dumps(
            {
                'check': 'toss_noon_reservation',
                'schedule_date': today.isoformat(),
                'approval_batch_created': bool(batch),
                'approval_batch_id': str(batch['id']) if batch else '',
                'publish_state': str(batch['publish_state']) if batch else '',
                'queued_items': queue_count,
            },
            ensure_ascii=False,
        )
    )


if __name__ == '__main__':
    main()
