from __future__ import annotations

from automation_store import _connect, scheduled_toss_queue_status
from kst_time import korea_today


def main() -> int:
    today = korea_today()
    with _connect() as conn:
        row = conn.execute(
            "SELECT to_regclass('public.scheduled_toss_publish_items') AS queue_table"
        ).fetchone()
    print(f"SCHEDULE_QUEUE_SCHEMA={bool((row or {}).get('queue_table'))}")
    for status, count in sorted(scheduled_toss_queue_status(today).items()):
        print(f"QUEUE_{status}={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
