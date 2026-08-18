from __future__ import annotations

from typing import Any, Callable

from automation_store import (
    record_toss_collection_failure,
    store_toss_collection,
)
from toss_open_api import (
    TossOpenApiError,
    best_selling_products,
    today_deal_products,
)


COLLECTION_SOURCES = {"best-selling", "today-deals"}


def _collector_for(source: str) -> Callable[[int], dict[str, object]]:
    normalized = str(source or "").strip().lower()
    if normalized == "best-selling":
        return lambda size: best_selling_products(size=size)
    if normalized == "today-deals":
        return lambda size: today_deal_products(size=min(size, 30))
    raise ValueError("지원하지 않는 토스 수집 목록입니다.")


def collect_toss_listing(source: str = "best-selling", size: int = 30) -> dict[str, Any]:
    """Fetch and persist one documented Toss listing page without issuing share links."""
    normalized = str(source or "").strip().lower()
    collector = _collector_for(normalized)
    bounded_size = min(max(int(size), 1), 30 if normalized == "today-deals" else 100)
    try:
        payload = collector(bounded_size)
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise TossOpenApiError("토스 Open API 상품 목록 항목 형식이 올바르지 않습니다.")
        stored = store_toss_collection(normalized, bounded_size, items)
    except (TossOpenApiError, RuntimeError, ValueError) as exc:
        try:
            failure = record_toss_collection_failure(normalized, bounded_size, exc)
        except RuntimeError:
            failure = {"source": normalized, "saved_count": 0, "status": "FAILED"}
        raise TossOpenApiError(
            f"토스 {normalized} 수집에 실패했습니다: {exc}",
            code=str(failure.get("status") or "FAILED"),
        ) from exc
    return {
        "source": normalized,
        "requested_size": bounded_size,
        "saved_count": int(stored["saved_count"]),
        "has_next": bool(payload.get("has_next")),
        "next_cursor_present": bool(payload.get("next_cursor")),
        "run_id": str(stored["id"]),
    }
