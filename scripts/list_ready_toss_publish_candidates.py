from __future__ import annotations

from automation_store import _connect


def main() -> None:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT p.taca_item_id, p.product_name, p.display_price,
                   p.best_rank, p.today_deal_rank,
                   (p.thumbnail_url <> '') AS has_image,
                   (l.short_url <> '') AS has_link
            FROM toss_products p
            JOIN toss_share_links l ON l.taca_item_id = p.taca_item_id
            WHERE p.is_sold_out = false
              AND p.thumbnail_url <> ''
              AND l.short_url <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM blog_posts b
                  WHERE b.platform = 'toss'
                    AND b.product_id = p.taca_item_id
                    AND b.status IN ('PUBLISHED', 'PUBLISHING', 'APPROVED', 'READY')
              )
            ORDER BY p.best_rank ASC NULLS LAST,
                     p.today_deal_rank ASC NULLS LAST,
                     p.last_seen_at DESC
            LIMIT 5
            """
        ).fetchall()
    print(f"READY_TOSS_CANDIDATE_COUNT={len(rows)}")
    for index, row in enumerate(rows, start=1):
        rank = row["best_rank"] or row["today_deal_rank"] or 0
        print(
            "|".join(
                [
                    str(index),
                    str(row["taca_item_id"]),
                    str(rank),
                    str(row["display_price"] or 0),
                    str(row["product_name"]),
                    "image=yes" if row["has_image"] else "image=no",
                    "link=yes" if row["has_link"] else "link=no",
                ]
            )
        )


if __name__ == "__main__":
    main()
