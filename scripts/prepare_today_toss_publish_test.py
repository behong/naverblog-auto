from __future__ import annotations

import json
from app import build_admin_toss_draft
from automation_store import _connect, create_scheduled_toss_publish_items
from telegram_approval import send_publication_approval
from toss_collector import collect_toss_listing
from kst_time import korea_today

TEST_ITEM_COUNT = 5
TEST_SOURCE = "toss-scheduled-test-master-v2"


def _already_prepared_today() -> bool:
    today = korea_today()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM publication_approval_batches
            WHERE source = %s AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            LIMIT 1
            """,
            (TEST_SOURCE, today),
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
                    AND b.status IN ('PUBLISHING', 'PUBLISHED', 'PUBLISH_UNKNOWN')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM scheduled_toss_publish_items q
                  WHERE q.schedule_date = %s AND q.product_id = p.taca_item_id
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
    if _already_prepared_today():
        print(json.dumps({"ok": True, "prepared": False, "reason": "already_prepared_today"}, ensure_ascii=False))
        return 0

    collect_toss_listing("best-selling", 30)
    prepared_items: list[dict[str, object]] = []
    skipped = 0
    for item_id in _candidate_ids(TEST_ITEM_COUNT * 3):
        if len(prepared_items) >= TEST_ITEM_COUNT:
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

    if len(prepared_items) != TEST_ITEM_COUNT:
        print(json.dumps({"ok": False, "prepared": False, "reason": "insufficient_publishable_candidates", "prepared_count": len(prepared_items), "skipped": skipped}, ensure_ascii=False))
        return 1

    batch = send_publication_approval(prepared_items, source=TEST_SOURCE, ttl_minutes=120)
    count = create_scheduled_toss_publish_items(
        str(batch["id"]),
        korea_today(),
        prepared_items,
    )
    print(json.dumps({"ok": True, "prepared": True, "master_batch_id": str(batch["id"]), "queued_count": count, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
