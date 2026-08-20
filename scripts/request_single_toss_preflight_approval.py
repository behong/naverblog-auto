import sys

from app import build_admin_toss_draft
from telegram_approval import send_publication_approval


def main() -> int:
    item_id = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not item_id:
        raise ValueError("토스 상품 ID가 필요합니다.")
    prepared = build_admin_toss_draft(item_id)
    draft = prepared.get("draft") if isinstance(prepared.get("draft"), dict) else {}
    batch = send_publication_approval(
        [
            {
                "product_id": prepared.get("product_id"),
                "product_name": prepared.get("product_name"),
                "price": prepared.get("price"),
                "title": draft.get("title"),
            }
        ],
        source="toss-preflight",
    )
    print("TOSS_PREFLIGHT_APPROVAL_REQUEST_SENT")
    print(f"PREFLIGHT_BATCH_PRESENT={bool(batch.get('id'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
