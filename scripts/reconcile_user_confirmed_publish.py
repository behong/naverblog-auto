from __future__ import annotations

import json
import sys

from automation_store import _connect, notify_telegram_approval


def main() -> int:
    post_url = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not post_url.startswith("https://blog.naver.com/"):
        raise ValueError("A confirmed Naver blog URL is required")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, summary
            FROM publication_approval_batches
            WHERE publish_state = 'PUBLISH_UNKNOWN'
            ORDER BY publish_finished_at DESC NULLS LAST
            LIMIT 1
            FOR UPDATE
            """
        ).fetchone()
        if not row:
            raise RuntimeError("No publish-unknown batch is available for reconciliation")
        summary = row.get("summary") if isinstance(row.get("summary"), list) else []
        if len(summary) != 1:
            raise RuntimeError("The publish-unknown batch must contain exactly one product")
        product_id = str((summary[0] or {}).get("product_id") or "").strip()
        if not product_id:
            raise RuntimeError("The publish-unknown batch product is missing")
        conn.execute(
            """
            UPDATE blog_posts
            SET status = 'PUBLISHED', naver_post_url = %s, published_at = COALESCE(published_at, now()),
                updated_at = now(), metadata = metadata || %s::jsonb
            WHERE platform = 'toss' AND product_id = %s
            """,
            (post_url, json.dumps({"publish_mode": "user_confirmed_url_reconciliation"}, ensure_ascii=False), product_id),
        )
        conn.execute(
            """
            UPDATE publication_approval_batches
            SET publish_state = 'PUBLISHED', publish_finished_at = now(),
                publish_error = 'user_confirmed_url_after_automatic_url_extraction_failure'
            WHERE id = %s
            """,
            (row["id"],),
        )
        conn.execute(
            """
            UPDATE scheduled_toss_publish_items
            SET status = 'PUBLISHED', finished_at = now(),
                error_message = 'user_confirmed_url_after_automatic_url_extraction_failure'
            WHERE release_batch_id = %s AND status = 'PUBLISH_UNKNOWN'
            """,
            (row["id"],),
        )
    notify_telegram_approval(f"✅ 사용자 확인으로 발행 URL을 기록했습니다.\n[TOSS] {post_url}")
    print("RECONCILED_PUBLISHED=True")
    print(f"POST_URL={post_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
