from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any
from urllib.parse import urlparse

from automation.coupang_pipeline import (
    CoupangCandidate,
    CoupangCandidateValidationError,
    build_coupang_approval_draft,
    validate_coupang_candidate,
)
from automation_store import _connect, notify_telegram_approval
from telegram_approval import send_publication_approval


COUPANG_APPROVAL_SOURCE = "coupang-publish"
COUPANG_TERMINAL_STATES = {"PUBLISHED", "PUBLISH_UNKNOWN", "FAILED_PRE_SUBMIT"}


def _text(value: object, field: str, maximum: int = 2000) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise ValueError(f"{field}을(를) 확인하지 못했습니다.")
    return cleaned[:maximum]


def _price(value: object, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}을(를) 확인하지 못했습니다.") from exc
    if parsed <= 0:
        raise ValueError(f"{field}은(는) 0원보다 커야 합니다.")
    return parsed


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} 목록을 확인하지 못했습니다.")
    result = tuple(" ".join(str(item or "").split())[:180] for item in value if str(item or "").strip())
    if len(result) < 3:
        raise ValueError(f"{field} 3개를 확인하지 못했습니다.")
    return result[:3]


def candidate_from_payload(payload: dict[str, Any]) -> CoupangCandidate:
    candidate = CoupangCandidate(
        product_id=_text(payload.get("product_id"), "쿠팡 상품 ID", 200),
        product_name=_text(payload.get("product_name"), "상품명", 500),
        composition=_text(payload.get("composition"), "구성", 300),
        product_url=_text(payload.get("product_url"), "쿠팡 상품 URL"),
        affiliate_url=_text(payload.get("affiliate_url"), "쿠팡 파트너스 링크"),
        original_image_url=_text(payload.get("original_image_url"), "원본 대표 이미지 URL"),
        normal_price=_price(payload.get("normal_price"), "정상가"),
        sale_price=_price(payload.get("sale_price"), "일반 할인가"),
        conditional_price=_price(payload.get("conditional_price"), "최저 조건부 가격"),
        price_condition=_text(payload.get("price_condition"), "실제 할인 조건", 300),
        description=_text(payload.get("description"), "상품 설명", 500),
        features=_string_list(payload.get("features"), "특징"),
        audiences=_string_list(payload.get("audiences"), "추천 대상"),
        source_image_verified=payload.get("source_image_verified") is True,
    )
    validate_coupang_candidate(candidate)
    return candidate


def candidate_payload(candidate: CoupangCandidate) -> dict[str, Any]:
    return {
        "product_id": candidate.product_id,
        "product_name": candidate.product_name,
        "composition": candidate.composition,
        "product_url": candidate.product_url,
        "affiliate_url": candidate.affiliate_url,
        "original_image_url": candidate.original_image_url,
        "normal_price": candidate.normal_price,
        "sale_price": candidate.sale_price,
        "conditional_price": candidate.conditional_price,
        "price_condition": candidate.price_condition,
        "description": candidate.description,
        "features": list(candidate.features),
        "audiences": list(candidate.audiences),
        "source_image_verified": candidate.source_image_verified,
    }


def request_coupang_publication_approval(payload: dict[str, Any], ttl_minutes: int = 30) -> dict[str, Any]:
    """Validate one fully reviewed product and send one Telegram approval request.

    This function never opens Naver or clicks a publish control.  It persists the
    complete validated candidate only inside the approval batch, keyed by the
    published product id, so the eventual publisher can reconstruct exactly the
    content the user approved.
    """
    candidate = candidate_from_payload(payload)
    if duplicate_coupang_product(candidate.product_id):
        raise ValueError("이미 발행 중이거나 발행된 쿠팡 상품은 다시 승인할 수 없습니다.")
    summary = [{
        "product_id": candidate.product_id,
        "product_name": candidate.product_name,
        "display_price": candidate.conditional_price,
        "normal_price": candidate.normal_price,
        "sale_price": candidate.sale_price,
        "conditional_price": candidate.conditional_price,
        "price_condition": candidate.price_condition,
        "affiliate_domain": (urlparse(candidate.affiliate_url).hostname or "").lower(),
        "source_image_verified": True,
        "candidate": candidate_payload(candidate),
    }]
    return send_publication_approval(summary, source=COUPANG_APPROVAL_SOURCE, ttl_minutes=ttl_minutes)


def duplicate_coupang_product(product_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM blog_posts WHERE platform = 'coupang' AND product_id = %s",
            (str(product_id or "").strip(),),
        ).fetchone()
    return bool(row and str(row.get("status") or "") in {"PUBLISHING", "PUBLISHED", "PUBLISH_UNKNOWN"})


def _approved_coupang_batch(batch_id: str = "", claim: bool = False) -> dict[str, Any] | None:
    filters = "status = 'APPROVED' AND source = %s AND item_count = 1"
    values: list[Any] = [COUPANG_APPROVAL_SOURCE]
    if batch_id:
        filters += " AND id = %s"
        values.append(uuid.UUID(str(batch_id)))
    if not batch_id:
        filters += " AND extension_claimed_at IS NULL"
    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT id, summary, source, status, extension_claimed_at, publish_state, created_at, decided_at
            FROM publication_approval_batches
            WHERE {filters}
            ORDER BY decided_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            tuple(values),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        if claim:
            updated = conn.execute(
                """
                UPDATE publication_approval_batches
                SET extension_claimed_at = now()
                WHERE id = %s AND extension_claimed_at IS NULL AND status = 'APPROVED'
                RETURNING id
                """,
                (result["id"],),
            ).fetchone()
            if not updated:
                return None
            result["extension_claimed_at"] = True
    return result


def approved_coupang_draft() -> dict[str, Any] | None:
    batch = _approved_coupang_batch()
    if not batch:
        return None
    summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
    if len(summary) != 1 or not isinstance(summary[0], dict):
        raise ValueError("쿠팡 승인 배치의 상품 정보를 확인하지 못했습니다.")
    raw_candidate = summary[0].get("candidate")
    if not isinstance(raw_candidate, dict):
        raise ValueError("쿠팡 승인 배치의 검증 정보를 확인하지 못했습니다.")
    candidate = candidate_from_payload(raw_candidate)
    draft = build_coupang_approval_draft(candidate)
    content = draft.get("draft") if isinstance(draft.get("draft"), dict) else {}
    product = {
        "platform": "coupang",
        "product_id": candidate.product_id,
        "product_name": candidate.product_name,
        "normal_price": candidate.normal_price,
        "sale_price": candidate.sale_price,
        "conditional_price": candidate.conditional_price,
        "price_condition": candidate.price_condition,
        "affiliate_url": candidate.affiliate_url,
        "naver_category": "42",
    }
    return {
        "batch_id": str(batch["id"]),
        "draft": {**content, "approvalBatchId": str(batch["id"]), "preflightOnly": False},
        "product": product,
        "naver_write_url": str(draft["naver_write_url"]),
        "original_image_url": candidate.original_image_url,
    }


def claim_coupang_approval(batch_id: str) -> bool:
    return _approved_coupang_batch(batch_id, claim=True) is not None


def _publish_values(product: dict[str, Any]) -> dict[str, Any]:
    if str(product.get("platform") or "").strip().lower() != "coupang":
        raise ValueError("쿠팡 전용 발행 요청만 허용됩니다.")
    values = {
        "platform": "coupang",
        "product_id": _text(product.get("product_id"), "쿠팡 상품 ID", 200),
        "product_name": _text(product.get("product_name"), "상품명", 500),
        "normal_price": _price(product.get("normal_price"), "정상가"),
        "sale_price": _price(product.get("sale_price"), "일반 할인가"),
        "conditional_price": _price(product.get("conditional_price"), "최저 조건부 가격"),
        "price_condition": _text(product.get("price_condition"), "실제 할인 조건", 300),
        "affiliate_url": _text(product.get("affiliate_url"), "쿠팡 파트너스 링크"),
        "naver_category": _text(product.get("naver_category"), "네이버 카테고리", 20),
    }
    if values["naver_category"] != "42":
        raise ValueError("쿠팡 네이버 카테고리는 42여야 합니다.")
    if not values["affiliate_url"].startswith("https://"):
        raise ValueError("쿠팡 파트너스 링크가 올바르지 않습니다.")
    if not values["normal_price"] >= values["sale_price"] >= values["conditional_price"]:
        raise ValueError("가격 순서가 검증되지 않았습니다.")
    return values


def begin_coupang_extension_publish(batch_id: str, product: dict[str, Any]) -> dict[str, Any]:
    parsed_id = uuid.UUID(str(batch_id))
    values = _publish_values(product)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, status, source, summary, extension_claimed_at, publish_state
            FROM publication_approval_batches WHERE id = %s FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("쿠팡 승인 배치를 찾지 못했습니다.")
        batch = dict(row)
        if batch.get("source") != COUPANG_APPROVAL_SOURCE or batch.get("status") != "APPROVED" or batch.get("extension_claimed_at") is None:
            raise ValueError("쿠팡 승인 배치가 발행 준비 상태가 아닙니다.")
        if str(batch.get("publish_state") or "NOT_STARTED") in {"PUBLISHING", "PUBLISHED", "PUBLISH_UNKNOWN"}:
            raise ValueError("이 쿠팡 승인 배치는 이미 발행을 시도했습니다.")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1 or str((summary[0] or {}).get("product_id") or "") != values["product_id"]:
            raise ValueError("승인 상품과 쿠팡 발행 요청이 일치하지 않습니다.")
        existing = conn.execute(
            "SELECT status FROM blog_posts WHERE platform = 'coupang' AND product_id = %s FOR UPDATE",
            (values["product_id"],),
        ).fetchone()
        if existing and str(existing.get("status") or "") in {"PUBLISHING", "PUBLISHED", "PUBLISH_UNKNOWN"}:
            raise ValueError("이 쿠팡 상품은 이미 발행 중이거나 발행됐습니다.")
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        metadata = json.dumps({"approval_batch_id": str(parsed_id), "publish_mode": "telegram_one_tap"}, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO blog_posts (platform, product_id, product_name, normal_price, sale_price, conditional_price,
                                    price_condition, affiliate_url, naver_category, status, metadata)
            VALUES (%(platform)s, %(product_id)s, %(product_name)s, %(normal_price)s, %(sale_price)s, %(conditional_price)s,
                    %(price_condition)s, %(affiliate_url)s, %(naver_category)s, 'PUBLISHING', %(metadata)s::jsonb)
            ON CONFLICT (platform, product_id) DO UPDATE SET
                product_name = EXCLUDED.product_name, normal_price = EXCLUDED.normal_price,
                sale_price = EXCLUDED.sale_price, conditional_price = EXCLUDED.conditional_price,
                price_condition = EXCLUDED.price_condition, affiliate_url = EXCLUDED.affiliate_url,
                naver_category = EXCLUDED.naver_category, status = 'PUBLISHING',
                metadata = blog_posts.metadata || EXCLUDED.metadata, updated_at = now()
            """,
            {**values, "metadata": metadata},
        )
        conn.execute(
            """
            UPDATE publication_approval_batches SET publish_state = 'PUBLISHING', publish_token_hash = %s,
                publish_started_at = now(), publish_finished_at = NULL, publish_error = '' WHERE id = %s
            """,
            (token_hash, parsed_id),
        )
    return {"publish_token": raw_token, "publish_state": "PUBLISHING"}


def record_coupang_pre_publish_failure(batch_id: str, error_message: str) -> dict[str, Any]:
    parsed_id = uuid.UUID(str(batch_id))
    reason = str(error_message or "쿠팡 네이버 자동 입력 또는 공개 전 검증에 실패했습니다.").strip()[:2000]
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, status, source, summary, publish_state FROM publication_approval_batches WHERE id = %s FOR UPDATE",
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("쿠팡 승인 배치를 찾지 못했습니다.")
        batch = dict(row)
        if batch.get("source") != COUPANG_APPROVAL_SOURCE or batch.get("status") != "APPROVED" or str(batch.get("publish_state") or "NOT_STARTED") != "NOT_STARTED":
            raise ValueError("쿠팡 승인 배치가 공개 전 실패 기록 상태가 아닙니다.")
        conn.execute(
            "UPDATE publication_approval_batches SET publish_state = 'FAILED_PRE_SUBMIT', publish_finished_at = now(), publish_error = %s WHERE id = %s",
            (reason, parsed_id),
        )
    notify_telegram_approval(f"❌ 쿠팡 네이버 공개 전 자동 입력이 중단됐습니다.\n사유: {reason}\n공개하지 않았습니다.")
    return {"batch_id": str(parsed_id), "outcome": "FAILED_PRE_SUBMIT"}


def record_coupang_publish_result(batch_id: str, publish_token: str, outcome: str, naver_post_url: str = "", error_message: str = "") -> dict[str, Any]:
    parsed_id = uuid.UUID(str(batch_id))
    raw_token = str(publish_token or "").strip()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest() if raw_token else ""
    result = str(outcome or "").strip().upper()
    if result not in COUPANG_TERMINAL_STATES:
        raise ValueError("지원하지 않는 쿠팡 발행 결과입니다.")
    clean_url = str(naver_post_url or "").strip()[:2000]
    reason = str(error_message or "").strip()[:2000]
    if result == "PUBLISHED" and not clean_url:
        raise ValueError("성공 결과에는 네이버 공개 URL이 필요합니다.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, source, summary, publish_state, publish_token_hash FROM publication_approval_batches WHERE id = %s FOR UPDATE",
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("쿠팡 승인 배치를 찾지 못했습니다.")
        batch = dict(row)
        if batch.get("source") != COUPANG_APPROVAL_SOURCE or batch.get("publish_state") != "PUBLISHING":
            raise ValueError("쿠팡 승인 배치가 발행 결과를 기다리는 상태가 아닙니다.")
        if not raw_token or not hmac.compare_digest(str(batch.get("publish_token_hash") or ""), token_hash):
            raise ValueError("쿠팡 발행 결과 토큰이 올바르지 않습니다.")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1:
            raise ValueError("쿠팡 승인 배치의 상품 수가 올바르지 않습니다.")
        product_id = str((summary[0] or {}).get("product_id") or "").strip()
        if result == "PUBLISHED":
            conn.execute(
                """UPDATE blog_posts SET status = 'PUBLISHED', naver_post_url = %s, published_at = now(), updated_at = now(),
                metadata = metadata || %s::jsonb WHERE platform = 'coupang' AND product_id = %s""",
                (clean_url, json.dumps({"approval_batch_id": str(parsed_id)}, ensure_ascii=False), product_id),
            )
        elif result == "FAILED_PRE_SUBMIT":
            conn.execute(
                "UPDATE blog_posts SET status = 'FAILED', updated_at = now(), metadata = metadata || %s::jsonb WHERE platform = 'coupang' AND product_id = %s",
                (json.dumps({"approval_batch_id": str(parsed_id), "publish_error": reason}, ensure_ascii=False), product_id),
            )
        conn.execute(
            "UPDATE publication_approval_batches SET publish_state = %s, publish_finished_at = now(), publish_error = %s WHERE id = %s",
            (result, reason, parsed_id),
        )
    name = _text((summary[0] or {}).get("product_name"), "상품명", 500)
    if result == "PUBLISHED":
        notify_telegram_approval(f"✅ 쿠팡 블로그 발행 완료\n상품: {name}\n공개 글: {clean_url}")
    elif result == "PUBLISH_UNKNOWN":
        notify_telegram_approval(
            f"⚠️ 쿠팡 발행 후 공개 URL을 자동 확인하지 못했습니다.\n상품: {name}\n"
            "중복 방지를 위해 자동 재클릭은 차단됐습니다.\n휴대폰 확인: https://blog.naver.com/sijm"
        )
    else:
        notify_telegram_approval(f"❌ 쿠팡 네이버 공개 전 검증 또는 버튼 탐색에 실패했습니다.\n사유: {reason or '알 수 없는 오류'}\n공개하지 않았습니다.")
    return {"batch_id": str(parsed_id), "outcome": result, "naver_post_url": clean_url}


__all__ = [
    "COUPANG_APPROVAL_SOURCE",
    "CoupangCandidateValidationError",
    "approved_coupang_draft",
    "begin_coupang_extension_publish",
    "claim_coupang_approval",
    "record_coupang_pre_publish_failure",
    "record_coupang_publish_result",
    "request_coupang_publication_approval",
]
