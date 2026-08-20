from __future__ import annotations

from automation_store import archive_terminal_scheduled_toss_items
from kst_time import korea_today


def main() -> int:
    today = korea_today()
    archived = archive_terminal_scheduled_toss_items(
        today,
        "today_actual_publish_test_active_queue_reset",
    )
    print(f"ARCHIVED_TERMINAL_TOSS_QUEUE_ITEMS={archived}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
