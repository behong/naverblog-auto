from __future__ import annotations

from automation_store import _connect


def main() -> int:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, status, extension_claimed_at, publish_state, publish_started_at, publish_finished_at
            FROM publication_approval_batches
            ORDER BY extension_claimed_at DESC NULLS LAST
            LIMIT 5
            """
        ).fetchall()
    for row in rows:
        print(
            "BATCH=" + str(row.get("id"))
            + "|STATUS=" + str(row.get("status"))
            + "|CLAIMED=" + str(bool(row.get("extension_claimed_at")))
            + "|PUBLISH_STATE=" + str(row.get("publish_state"))
            + "|STARTED=" + str(bool(row.get("publish_started_at")))
            + "|FINISHED=" + str(bool(row.get("publish_finished_at")))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
