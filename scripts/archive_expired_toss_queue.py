from __future__ import annotations

import argparse
from datetime import date, timedelta

from automation_store import _connect, archive_terminal_scheduled_toss_items
from kst_time import korea_today


ARCHIVE_REASON = "expired_kst_date_rollover_before_release"


def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive a stale Toss scheduled queue after a KST date rollover.")
    parser.add_argument("--schedule-date", default=(korea_today() - timedelta(days=1)).isoformat())
    parser.add_argument("--apply", action="store_true", help="Perform the state change and archive. Defaults to preview only.")
    args = parser.parse_args()
    schedule_date = _parse_date(args.schedule_date)

    with _connect() as conn:
        released = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s AND status = 'RELEASED'
            """,
            (schedule_date,),
        ).fetchone()
        queued = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s AND status = 'QUEUED'
            """,
            (schedule_date,),
        ).fetchone()

    released_count = int((released or {}).get("count") or 0)
    queued_count = int((queued or {}).get("count") or 0)
    print(f"SCHEDULE_DATE={schedule_date.isoformat()}")
    print(f"RELEASED_BLOCKING_COUNT={released_count}")
    print(f"QUEUED_STALE_COUNT={queued_count}")

    if released_count:
        print("ARCHIVE_SAFE_TO_APPLY=FALSE")
        print("REASON=release_in_progress_requires_manual_reconciliation")
        return 1

    print("ARCHIVE_SAFE_TO_APPLY=TRUE")
    if not args.apply:
        print("PREVIEW_ONLY=TRUE")
        return 0

    with _connect() as conn:
        rows = conn.execute(
            """
            UPDATE scheduled_toss_publish_items
            SET status = 'SKIPPED', finished_at = now(), error_message = %s
            WHERE schedule_date = %s AND status = 'QUEUED'
            RETURNING id
            """,
            (ARCHIVE_REASON, schedule_date),
        ).fetchall()
    archived = archive_terminal_scheduled_toss_items(schedule_date, ARCHIVE_REASON)
    print(f"SKIPPED_STALE_COUNT={len(rows)}")
    print(f"ARCHIVED_TERMINAL_COUNT={archived}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
