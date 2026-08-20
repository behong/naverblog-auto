from __future__ import annotations

import sys

from toss_open_api import product_detail


def main() -> int:
    item_id = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not item_id.isdigit():
        print("CANDIDATE_ID_REQUIRED")
        return 2
    detail = product_detail(taca_item_id=item_id)
    images = detail.get("images") if isinstance(detail.get("images"), list) else []
    print(f"CANDIDATE_DETAIL_FOUND={bool(detail)}")
    print(f"CANDIDATE_SOLD_OUT={bool(detail.get('is_sold_out'))}")
    print(f"CANDIDATE_PRICE_VALID={str(detail.get('price') or '').isdigit()}")
    print(f"CANDIDATE_ORIGINAL_IMAGE_COUNT={len(images)}")
    print(f"CANDIDATE_IMAGE_URL_VALID={bool(images and str(images[0]).startswith('https://'))}")
    print(f"CANDIDATE_TITLE={str(detail.get('title') or '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
