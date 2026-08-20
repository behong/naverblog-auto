from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup


PRICE_PATTERN = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*|\d+)\s*원")
CONDITIONAL_LABELS = ("와우할인", "쿠폰할인", "회원할인")


class CoupangDetailVerificationError(ValueError):
    pass


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _parse_price(value: str) -> int | None:
    matches = PRICE_PATTERN.findall(value)
    return int(matches[-1].replace(",", "")) if matches else None


def _last_price_before(text: str, label: str) -> int | None:
    index = text.find(label)
    if index < 0:
        return None
    return _parse_price(text[:index])


def _is_original_coupang_image(url: str) -> bool:
    lowered = url.lower()
    return (
        url.startswith("https://")
        and "coupangcdn.com/" in lowered
        and "/thumbnails/remote/" not in lowered
        and not lowered.endswith(".svg")
    )


def fetch_coupang_detail(product_url: str, *, timeout_seconds: int = 20) -> dict[str, Any]:
    response = requests.get(
        product_url,
        timeout=timeout_seconds,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NaverBlogAutoCouponVerifier/1.0)"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = _clean(soup.get_text(" ", strip=True))
    title_meta = soup.select_one('meta[property="og:title"], meta[name="title"]')
    image_meta = soup.select_one('meta[property="og:image"]')
    title = _clean(title_meta.get("content") if title_meta else "")
    image_url = _clean(image_meta.get("content") if image_meta else "")

    conditional_label = next((label for label in CONDITIONAL_LABELS if label in text), "")
    general_price = _last_price_before(text, "쿠팡판매가")
    conditional_price = _last_price_before(text, conditional_label) if conditional_label else None
    return {
        "product_url": product_url,
        "product_name": title,
        "source_image_url": image_url,
        "source_image_verified": _is_original_coupang_image(image_url),
        "general_price": general_price,
        "lowest_conditional_price": conditional_price,
        "conditional_price_condition": conditional_label,
        "detail_page_fetched": True,
    }


def merge_partner_link_with_detail(link_record: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    if not link_record.get("affiliate_url") or not link_record.get("product_url"):
        raise CoupangDetailVerificationError("검증된 파트너스 링크와 상품 URL이 필요합니다.")
    if not detail.get("detail_page_fetched"):
        raise CoupangDetailVerificationError("상품 상세 페이지를 확인하지 못했습니다.")
    product_name = _clean(detail.get("product_name"))
    if not product_name:
        raise CoupangDetailVerificationError("상품 상세 페이지에서 상품명을 확인하지 못했습니다.")
    general_price = detail.get("general_price")
    if not isinstance(general_price, int) or general_price <= 0:
        raise CoupangDetailVerificationError("상품 상세 페이지에서 일반 할인가를 확인하지 못했습니다.")

    merged = dict(link_record)
    merged.update(
        {
            "product_name": product_name,
            "general_price": general_price,
            "lowest_conditional_price": detail.get("lowest_conditional_price"),
            "conditional_price_condition": detail.get("conditional_price_condition") or "",
            "source_image_url": detail.get("source_image_url") or "",
            "source_image_verified": bool(detail.get("source_image_verified")),
            "requires_product_detail_verification": False,
            "requires_conditional_price_verification": detail.get("lowest_conditional_price") is None,
            "approval_only": True,
        }
    )
    return merged
