from __future__ import annotations

from automation_store import _connect
from kst_time import korea_today


def main() -> int:
    today = korea_today()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT q.sequence_no, q.status AS queue_status, q.released_at, q.finished_at,
                   COALESCE(q.error_message, '') AS queue_error,
                   b.status AS batch_status, b.publish_state, b.extension_claimed_at,
                   b.publish_started_at, b.publish_finished_at,
                   COALESCE(b.publish_error, '') AS batch_error
            FROM scheduled_toss_publish_items q
            LEFT JOIN publication_approval_batches b ON b.id = q.release_batch_id
            WHERE q.schedule_date = %s AND q.status = 'RELEASED'
            ORDER BY q.sequence_no
            """,
            (today,),
        ).fetchall()
    print(f"TODAY={today.isoformat()}")
    if not rows:
        print("ACTIVE_RELEASED=NONE")
        return 0
    for row in rows:
        print(
            "ACTIVE_RELEASED|sequence={sequence_no}|queue={queue_status}|claimed={claimed}|"
            "batch={batch_status}|publish_state={publish_state}|started={started}|finished={finished}|"
            "queue_error={queue_error}|batch_error={batch_error}".format(
                sequence_no=row["sequence_no"],
                queue_status=row["queue_status"],
                claimed=bool(row["extension_claimed_at"]),
                batch_status=row["batch_status"] or "",
                publish_state=row["publish_state"] or "",
                started=bool(row["publish_started_at"]),
                finished=bool(row["publish_finished_at"]),
                queue_error=row["queue_error"],
                batch_error=row["batch_error"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
