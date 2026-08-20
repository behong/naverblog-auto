from __future__ import annotations

import argparse
import json

from automation_store import _connect, create_scheduled_toss_publish_items
from kst_time import korea_today
from telegram_approval import send_publication_approval


def main() -> int:
    parser = argparse.ArgumentParser(description="Request Telegram approval for a prepared Toss draft window.")
    parser.add_argument("--window-key", required=True)
    args = parser.parse_args()
    window_key = str(args.window_key).strip().lower()
    if not window_key:
        raise ValueError("window key is required")

    today = korea_today()
    prepared_source = f"toss-draft-window:{window_key}"
    approval_source = f"{prepared_source}:approval"
    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT id, status
            FROM publication_approval_batches
            WHERE source = %s AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (approval_source, today),
        ).fetchone()
        if existing and str(existing["status"]) in {"PENDING", "APPROVED"}:
            print(json.dumps({"ok": True, "requested": False, "reason": "approval_already_active", "status": str(existing["status"])}, ensure_ascii=False))
            return 0

        prepared = conn.execute(
            """
            SELECT id, summary
            FROM publication_approval_batches
            WHERE source = %s AND status = 'HELD' AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (prepared_source, today),
        ).fetchone()
        if not prepared:
            raise RuntimeError("오늘 준비된 보류 초안 창을 찾지 못했습니다.")
        queued = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s AND master_batch_id = %s AND status = 'QUEUED'
            """,
            (today, prepared["id"]),
        ).fetchone()
        queued_count = int((queued or {}).get("count") or 0)
        summary = prepared["summary"] if isinstance(prepared["summary"], list) else []
        if not summary:
            raise RuntimeError("승인 요청에 사용할 초안 요약이 없습니다.")
        if queued_count and len(summary) != queued_count:
            raise RuntimeError("승인 요약과 미발행 대기열 수가 일치하지 않습니다.")

    batch = send_publication_approval(summary, source=approval_source, ttl_minutes=120)
    if queued_count:
        with _connect() as conn:
            updated = conn.execute(
                """
                UPDATE scheduled_toss_publish_items
                SET master_batch_id = %s
                WHERE schedule_date = %s AND master_batch_id = %s AND status = 'QUEUED'
                RETURNING id
                """,
                (batch["id"], today, prepared["id"]),
            ).fetchall()
        if len(updated) != queued_count:
            raise RuntimeError("승인 배치와 대기열 연결 수가 일치하지 않습니다.")
        recovery_mode = "relinked_existing_queue"
    else:
        created = create_scheduled_toss_publish_items(str(batch["id"]), today, summary)
        if created != len(summary):
            raise RuntimeError("승인 배치의 새 대기열 생성 수가 일치하지 않습니다.")
        queued_count = created
        recovery_mode = "created_missing_queue"

    print(json.dumps({"ok": True, "requested": True, "window_key": window_key, "queued_count": queued_count, "recovery_mode": recovery_mode, "approval_batch_id": str(batch["id"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
