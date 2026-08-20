from __future__ import annotations

import argparse
import json
from app import build_admin_toss_draft
from automation_store import _connect, create_scheduled_toss_publish_items
from kst_time import korea_today
from telegram_approval import send_publication_approval
from toss_collector import collect_toss_listing


def _already_prepared_today(window_key: str) -> bool:
    today = korea_today()
    source = f"toss-draft-window:{window_key}"
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM publication_approval_batches
            WHERE source = %s
              AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            LIMIT 1
            """,
            (source, today),
        ).fetchone()
    return bool(row)


def _candidate_ids(limit: int) -> list[str]:
    today = korea_today()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT p.taca_item_id
            FROM toss_products p
            JOIN toss_share_links l ON l.taca_item_id = p.taca_item_id
            WHERE p.is_sold_out = false
              AND p.thumbnail_url <> ''
              AND l.short_url <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM blog_posts b
                  WHERE b.platform = 'toss'
                    AND b.product_id = p.taca_item_id
                    AND b.status IN ('PUBLISHING', 'PUBLISHED')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM scheduled_toss_publish_items q
                  WHERE q.schedule_date = %s
                    AND q.product_id = p.taca_item_id
              )
            ORDER BY p.best_rank ASC NULLS LAST,
                     p.today_deal_rank ASC NULLS LAST,
                     p.last_seen_at DESC
            LIMIT %s
            """,
            (today, limit),
        ).fetchall()
    return [str(row["taca_item_id"]) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a held Toss draft window without publishing.")
    parser.add_argument("--window-key", required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()

    window_key = str(args.window_key).strip().lower()
    count = int(args.count)
    if not window_key or count < 1 or count > 10:
        raise ValueError("window key and count must be valid")
    if _already_prepared_today(window_key):
        print(json.dumps({"ok": True, "prepared": False, "reason": "already_prepared_for_window"}, ensure_ascii=False))
        return 0

    collect_toss_listing("best-selling", 30)
    prepared_items: list[dict[str, object]] = []
    skipped = 0
    for item_id in _candidate_ids(count * 3):
        if len(prepared_items) >= count:
            break
        try:
            draft = build_admin_toss_draft(item_id)
        except (ValueError, RuntimeError):
            skipped += 1
            continue
        prepared_items.append(
            {
                "product_id": draft["product_id"],
                "product_name": draft["product_name"],
                "price": draft["price"],
                "title": (draft.get("draft") or {}).get("title", ""),
            }
        )

    if not prepared_items:
        print(json.dumps({"ok": False, "prepared": False, "reason": "no_publishable_candidates", "skipped": skipped}, ensure_ascii=False))
        return 1

    # 시간대별 준비 완료 후 텔레그램에 단일 승인 요청을 전송한다.
    # 승인 전에는 대기열이 RELEASED로 전환될 수 없으므로 공개 발행은 시작되지 않는다.
    batch = send_publication_approval(
        prepared_items,
        source=f"toss-draft-window:{window_key}",
        ttl_minutes=120,
    )
    queue_count = create_scheduled_toss_publish_items(
        str(batch["id"]),
        korea_today(),
        prepared_items,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "prepared": True,
                "window_key": window_key,
                "queued_count": queue_count,
                "skipped": skipped,
                "publish_state": "PENDING_APPROVAL",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
