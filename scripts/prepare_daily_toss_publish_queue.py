from __future__ import annotations

import json
from app import build_admin_toss_draft
from automation_store import _connect, create_scheduled_toss_publish_items
from telegram_approval import send_publication_approval
from toss_collector import collect_toss_listing
from kst_time import korea_today

MAX_DAILY_ITEMS = 10
DAILY_APPROVAL_TTL_MINUTES = 120


def _already_prepared_today() -> bool:
    today = korea_today()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM scheduled_toss_publish_items WHERE schedule_date = %s LIMIT 1",
            (today,),
        ).fetchone()
    return bool(row)


def _candidate_ids(limit: int) -> list[str]:
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
                  WHERE q.schedule_date = %s AND q.product_id = p.taca_item_id
              )
            ORDER BY p.best_rank ASC NULLS LAST,
                     p.today_deal_rank ASC NULLS LAST,
                     p.last_seen_at DESC
            LIMIT %s
            """,
            (korea_today(), limit),
        ).fetchall()
    return [str(row["taca_item_id"]) for row in rows]


def main() -> int:
    if _already_prepared_today():
        print(json.dumps({"ok": True, "prepared": False, "reason": "already_prepared_today"}, ensure_ascii=False))
        return 0
    collect_toss_listing("best-selling", 30)
    prepared_items: list[dict[str, object]] = []
    skipped = 0
    for item_id in _candidate_ids(MAX_DAILY_ITEMS * 3):
        if len(prepared_items) >= MAX_DAILY_ITEMS:
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
    batch = send_publication_approval(
        prepared_items,
        source="toss-scheduled-daily-master",
        ttl_minutes=DAILY_APPROVAL_TTL_MINUTES,
    )
    count = create_scheduled_toss_publish_items(
        str(batch["id"]),
        korea_today(),
        prepared_items,
    )
    print(json.dumps({"ok": True, "prepared": True, "queued_count": count, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
