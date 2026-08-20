from __future__ import annotations

from automation_store import _connect


def main() -> int:
    with _connect() as conn:
        batch = conn.execute(
            """
            SELECT id, status, extension_claimed_at IS NOT NULL AS claimed,
                   publish_state, publish_started_at IS NOT NULL AS publish_started,
                   publish_finished_at IS NOT NULL AS publish_finished,
                   publish_error, summary
            FROM publication_approval_batches
            ORDER BY decided_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        product_id = str(((batch or {}).get("summary") or [{}])[0].get("product_id") or "")
        post = conn.execute(
            """
            SELECT status, naver_post_url, published_at IS NOT NULL AS published,
                   metadata
            FROM blog_posts
            WHERE platform = 'toss' AND product_id = %s
            """,
            (product_id,),
        ).fetchone() if product_id else None
    print(f"BATCH_PRESENT={bool(batch)}")
    print(f"BATCH_STATUS={str((batch or {}).get('status') or '')}")
    print(f"BATCH_CLAIMED={bool((batch or {}).get('claimed'))}")
    print(f"PUBLISH_STATE={str((batch or {}).get('publish_state') or '')}")
    print(f"PUBLISH_STARTED={bool((batch or {}).get('publish_started'))}")
    print(f"PUBLISH_FINISHED={bool((batch or {}).get('publish_finished'))}")
    print(f"PUBLISH_ERROR={str((batch or {}).get('publish_error') or '')}")
    print(f"POST_PRESENT={bool(post)}")
    print(f"POST_STATUS={str((post or {}).get('status') or '')}")
    print(f"POST_URL_PRESENT={bool((post or {}).get('naver_post_url') or '')}")
    print(f"POST_URL={str((post or {}).get('naver_post_url') or '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
