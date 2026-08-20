from __future__ import annotations

import urllib.parse
from typing import Any


AFFILIATE_HOSTS = {"link.coupang.com", "coupa.ng"}


class CoupangLinkResultError(ValueError):
    pass


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _positive_int(value: object, field: str) -> int:
    try:
        parsed = int(str(value or ""))
    except (TypeError, ValueError) as exc:
        raise CoupangLinkResultError(f"{field}을(를) 확인하지 못했습니다.") from exc
    if parsed <= 0:
        raise CoupangLinkResultError(f"{field}은(는) 0보다 커야 합니다.")
    return parsed


def _valid_affiliate_url(value: object) -> str:
    url = _clean(value)
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in AFFILIATE_HOSTS:
        raise CoupangLinkResultError("검증된 쿠팡 파트너스 링크가 없습니다.")
    return url


def _first_success_frame(payload: object) -> dict[str, Any]:
    values = payload if isinstance(payload, dict) else {}
    frames = values.get("frames") if isinstance(values.get("frames"), list) else []
    for frame in frames:
        result = frame.get("result") if isinstance(frame, dict) and isinstance(frame.get("result"), dict) else {}
        if result.get("ok") and result.get("link_detected"):
            return result
    raise CoupangLinkResultError("파트너스 링크 생성 성공 결과를 찾지 못했습니다.")


def parse_coupang_partner_link_result(payload: object) -> dict[str, Any]:
    """Parse a link-only result. It never creates an approval batch, queue, or post."""
    result = _first_success_frame(payload)
    page_url = _clean(result.get("page_url"))
    parsed_page = urllib.parse.urlparse(page_url)
    # Partners is a hash-route SPA: product parameters are after '?' inside the URL fragment.
    fragment_query = parsed_page.fragment.partition("?")[2]
    query = urllib.parse.parse_qs(parsed_page.query or fragment_query)

    product_id = _positive_int(query.get("product[productId]", [""])[0], "쿠팡 상품 ID")
    item_id = _positive_int(query.get("product[itemId]", [""])[0], "쿠팡 아이템 ID")
    vendor_item_id = _positive_int(query.get("product[vendorItemId]", [""])[0], "쿠팡 판매자 아이템 ID")
    normal_price = _positive_int(query.get("product[originPrice]", [""])[0], "정상가")
    sale_price = _positive_int(query.get("product[salesPrice]", [""])[0], "일반 할인가")
    if normal_price < sale_price:
        raise CoupangLinkResultError("정상가와 일반 할인가의 순서가 올바르지 않습니다.")

    title = _clean(query.get("product[title]", [""])[0])
    image_url = _clean(query.get("product[image]", [""])[0])
    if not title or not image_url.startswith("https://") or "coupangcdn.com/" not in image_url.lower():
        raise CoupangLinkResultError("상품명 또는 쿠팡 CDN 이미지를 확인하지 못했습니다.")
    if _clean(query.get("product[travel]", [""])[0]).lower() == "true":
        raise CoupangLinkResultError("여행 상품은 자동 발행 후보에서 제외합니다.")

    urls = [_valid_affiliate_url(value) for value in (result.get("generated_urls") or [])]
    # A coupa.ng URL is the shortest verified affiliate URL, otherwise retain the first link.coupang.com URL.
    affiliate_url = next((url for url in urls if urllib.parse.urlparse(url).hostname == "coupa.ng"), urls[0] if urls else "")
    if not affiliate_url:
        raise CoupangLinkResultError("검증된 쿠팡 파트너스 링크가 없습니다.")

    return {
        "platform": "coupang",
        "product_id": str(product_id),
        "item_id": str(item_id),
        "vendor_item_id": str(vendor_item_id),
        "product_name": title,
        "normal_price": normal_price,
        "sale_price": sale_price,
        "affiliate_url": affiliate_url,
        "product_url": f"https://www.coupang.com/vp/products/{product_id}?itemId={item_id}&vendorItemId={vendor_item_id}",
        "preview_image_url": image_url,
        "source_image_verified": False,
        "requires_product_detail_verification": True,
        "requires_conditional_price_verification": True,
        "approval_only": True,
    }
