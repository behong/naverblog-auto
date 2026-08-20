"""Hold only pending today test-publish approval batches after an incomplete queue creation."""

from automation_store import _connect
from kst_time import korea_today

SOURCE = "toss-scheduled-test-master"


def main() -> None:
    today = korea_today()
    with _connect() as conn:
        rows = conn.execute(
            """
            UPDATE publication_approval_batches
            SET status = 'HELD', decided_at = now()
            WHERE source = %s
              AND status = 'PENDING'
              AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            RETURNING id
            """,
            (SOURCE, today),
        ).fetchall()
    print(f"HELD_INCOMPLETE_TEST_BATCH_COUNT={len(rows)}")


if __name__ == "__main__":
    main()
