from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


TRAVEL_KEYWORDS = ("리조트", "숙박", "호텔", "여행", "평창", "제천", "항공")


@dataclass(frozen=True)
class GoldboxPreview:
    candidate_id: str
    product_name: str
    preview_image_url: str
    normal_price: int
    sale_price: int

    @property
    def discount_rate(self) -> int:
        if self.normal_price <= 0:
            return 0
        return round((self.normal_price - self.sale_price) * 100 / self.normal_price)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _source_is_coupang_image(url: str) -> bool:
    lowered = url.lower()
    return lowered.startswith("https://") and "coupangcdn.com/" in lowered


def normalize_goldbox_candidates(raw_candidates: Iterable[object]) -> tuple[list[GoldboxPreview], dict[str, int]]:
    """Return review-only previews; this function never creates a link, approval batch, queue, or post."""
    kept: list[GoldboxPreview] = []
    seen: set[str] = set()
    summary = {
        "input": 0,
        "kept": 0,
        "excluded_duplicate": 0,
        "excluded_incomplete_title": 0,
        "excluded_travel": 0,
        "excluded_price": 0,
        "excluded_image": 0,
    }
    for raw in raw_candidates:
        summary["input"] += 1
        values = raw if isinstance(raw, dict) else {}
        candidate_id = _clean(values.get("candidate_id"))
        name = _clean(values.get("product_name"))
        image_url = _clean(values.get("preview_image_url"))
        normal_price = _positive_int(values.get("displayed_normal_price"))
        sale_price = _positive_int(values.get("displayed_sale_price"))

        if not candidate_id or candidate_id in seen:
            summary["excluded_duplicate"] += 1
            continue
        seen.add(candidate_id)
        if not name or "…" in name or "..." in name:
            summary["excluded_incomplete_title"] += 1
            continue
        if any(keyword in name for keyword in TRAVEL_KEYWORDS):
            summary["excluded_travel"] += 1
            continue
        if normal_price is None or sale_price is None or normal_price < sale_price:
            summary["excluded_price"] += 1
            continue
        if not _source_is_coupang_image(image_url):
            summary["excluded_image"] += 1
            continue
        kept.append(
            GoldboxPreview(
                candidate_id=candidate_id,
                product_name=name,
                preview_image_url=image_url,
                normal_price=normal_price,
                sale_price=sale_price,
            )
        )
        summary["kept"] += 1

    kept.sort(key=lambda item: (item.sale_price, -item.discount_rate, item.product_name))
    return kept, summary


def to_review_payload(previews: Iterable[GoldboxPreview], summary: dict[str, int]) -> dict[str, Any]:
    return {
        "source": "coupang-goldbox-preview",
        "review_only": True,
        "summary": dict(summary),
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "product_name": item.product_name,
                "preview_image_url": item.preview_image_url,
                "displayed_normal_price": item.normal_price,
                "displayed_sale_price": item.sale_price,
                "displayed_discount_rate": item.discount_rate,
                "requires_product_detail_verification": True,
                "requires_partner_link_generation": True,
                "source_image_verified": False,
            }
            for item in previews
        ],
    }
