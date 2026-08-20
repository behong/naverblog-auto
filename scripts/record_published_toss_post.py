from __future__ import annotations

from automation_store import toss_product_with_share_link, upsert_post

ITEM_ID = "2588220177"
POST_URL = "https://blog.naver.com/sijm/224382513429"


def main() -> int:
    product = toss_product_with_share_link(ITEM_ID)
    if not product:
        raise RuntimeError("published Toss product is missing")
    result = upsert_post(
        {
            "platform": "toss",
            "product_id": ITEM_ID,
            "product_name": str(product.get("product_name") or ""),
            "sale_price": product.get("display_price"),
            "affiliate_url": str(product.get("short_url") or ""),
            "naver_category": "39",
            "naver_post_url": POST_URL,
            "status": "PUBLISHED",
            "metadata": {
                "publish_mode": "user_confirmed_single_test",
                "source": "telegram_approved_extension_autofill",
            },
        }
    )
    print(f"PUBLISHED_POST_RECORDED={str(result.get('status') or '') == 'PUBLISHED'}")
    print(f"PUBLISHED_PRODUCT_ID_MATCH={str(result.get('product_id') or '') == ITEM_ID}")
    print(f"PUBLISHED_URL_MATCH={str(result.get('naver_post_url') or '') == POST_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
