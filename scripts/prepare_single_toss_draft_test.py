from __future__ import annotations

import sys

from app import build_admin_toss_draft


def main() -> int:
    item_id = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    result = build_admin_toss_draft(item_id)
    draft = result.get("draft") if isinstance(result.get("draft"), dict) else {}
    print(f"SINGLE_DRAFT_PRODUCT_ID={result.get('product_id')}")
    print(f"SINGLE_DRAFT_PRICE_VALID={int(result.get('price') or 0) > 0}")
    print(f"SINGLE_DRAFT_TITLE_VALID={bool(draft.get('title'))}")
    print(f"SINGLE_DRAFT_BODY_VALID={bool(draft.get('body'))}")
    print(f"SINGLE_DRAFT_IMAGE_PROXY_VALID={str(draft.get('imageUrl') or '').startswith('https://blogauto.hongzi.us/api/image?url=')}")
    print(f"SINGLE_DRAFT_TAGS_VALID={bool(draft.get('tags'))}")
    print(f"SINGLE_DRAFT_CATEGORY={result.get('category_no')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
