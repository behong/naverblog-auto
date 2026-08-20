from __future__ import annotations

import sys

from automation_store import _connect, record_extension_pre_publish_failure


def main() -> int:
    reason = str(sys.argv[1] if len(sys.argv) > 1 else "공개 전 자동 입력이 중단되었습니다.").strip()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM publication_approval_batches
            WHERE status = 'APPROVED'
              AND extension_claimed_at IS NOT NULL
              AND publish_state = 'NOT_STARTED'
            ORDER BY extension_claimed_at DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("No claimed pre-publish batch is awaiting reconciliation")
    result = record_extension_pre_publish_failure(str(row["id"]), reason)
    print(f"FAILED_PRE_SUBMIT_RECORDED={result.get('outcome') == 'FAILED_PRE_SUBMIT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
