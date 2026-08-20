from __future__ import annotations

import os
from typing import Any, Callable

from automation_store import (
    admin_toss_publisher_id,
    ensure_toss_share_link,
    record_toss_collection_failure,
    store_toss_collection,
)
from toss_open_api import (
    TossOpenApiError,
    best_selling_products,
    issue_share_link,
    today_deal_products,
)


COLLECTION_SOURCES = {"best-selling", "today-deals"}
AUTO_ISSUE_SHARE_LINKS = os.getenv(
    "TOSS_AUTO_ISSUE_SHARE_LINKS", "true"
).strip().lower() not in {"0", "false", "no", "off"}
QUOTA_EXCEEDED_CODE = "SHARELINK_OPENAPI_QUOTA_EXCEEDED"


def _collector_for(source: str) -> Callable[[int], dict[str, object]]:
    normalized = str(source or "").strip().lower()
    if normalized == "best-selling":
        return lambda size: best_selling_products(size=size)
    if normalized == "today-deals":
        return lambda size: today_deal_products(size=min(size, 30))
    raise ValueError("지원하지 않는 토스 수집 목록입니다.")


def issue_toss_share_link(taca_item_id: str) -> dict[str, Any]:
    """Issue one tracked link for a stored, saleable Toss item option."""
    publisher_id = admin_toss_publisher_id()
    if not publisher_id:
        raise TossOpenApiError("토스 퍼블리셔 UUID 환경 설정을 먼저 확인해 주세요.")
    try:
        return ensure_toss_share_link(
            taca_item_id,
            lambda selected_id: issue_share_link(selected_id, publisher_id),
        )
    except (RuntimeError, ValueError, TossOpenApiError) as exc:
        code = exc.code if isinstance(exc, TossOpenApiError) else ""
        raise TossOpenApiError(
            f"토스 쉐어링크 발급에 실패했습니다: {exc}", code=code
        ) from exc


def auto_issue_toss_share_links(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Issue links for newly collected saleable options, reusing any stored link."""
    summary: dict[str, Any] = {
        "enabled": AUTO_ISSUE_SHARE_LINKS,
        "candidates": 0,
        "issued": 0,
        "reused": 0,
        "skipped_sold_out": 0,
        "skipped_invalid": 0,
        "failed": 0,
        "quota_exceeded": False,
    }
    if not AUTO_ISSUE_SHARE_LINKS:
        return summary
    if not admin_toss_publisher_id():
        summary["failed"] = 1
        summary["error"] = "publisher_not_configured"
        return summary

    seen_ids: set[str] = set()
    for item in items:
        item_id = str(item.get("taca_item_id") or "").strip()
        if not item_id.isdigit() or item_id in seen_ids:
            summary["skipped_invalid"] += 1
            continue
        seen_ids.add(item_id)
        if bool(item.get("is_sold_out")):
            summary["skipped_sold_out"] += 1
            continue
        summary["candidates"] += 1
        try:
            result = issue_toss_share_link(item_id)
        except TossOpenApiError as exc:
            if exc.code == QUOTA_EXCEEDED_CODE:
                summary["quota_exceeded"] = True
                break
            summary["failed"] += 1
            continue
        if bool(result.get("reused")):
            summary["reused"] += 1
        else:
            summary["issued"] += 1
    return summary


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
        try:
            auto_issuance = auto_issue_toss_share_links(items)
        except (RuntimeError, ValueError):
            auto_issuance = {
                "enabled": AUTO_ISSUE_SHARE_LINKS,
                "candidates": 0,
                "issued": 0,
                "reused": 0,
                "skipped_sold_out": 0,
                "skipped_invalid": 0,
                "failed": 1,
                "quota_exceeded": False,
                "error": "automation_error",
            }
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
        "auto_issuance": auto_issuance,
    }
