from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from automation.content import ContentValidationError, Product, build_coupang_post


COUPANG_AFFILIATE_HOSTS = {"link.coupang.com", "coupa.ng"}
COUPANG_PRODUCT_HOST_SUFFIXES = ("coupang.com",)
COUPANG_IMAGE_HOST_SUFFIXES = ("coupangcdn.com",)


class CoupangCandidateValidationError(ValueError):
    """A Coupang candidate is not sufficiently verified for an approval draft."""


@dataclass(frozen=True)
class CoupangCandidate:
    product_id: str
    product_name: str
    composition: str
    product_url: str
    affiliate_url: str
    original_image_url: str
    original_image_urls: tuple[str, ...] = ()
    normal_price: int | None = None
    sale_price: int | None = None
    conditional_price: int | None = None
    price_condition: str = ""
    description: str = ""
    features: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ()
    source_image_verified: bool = False
    current_price: int | None = None


def _clean(value: object, field: str, maximum: int = 500) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise CoupangCandidateValidationError(f"{field}을(를) 확인하지 못했습니다.")
    if len(cleaned) > maximum:
        raise CoupangCandidateValidationError(f"{field}이(가) 너무 깁니다.")
    return cleaned


def _positive_price(value: object, field: str) -> int:
    try:
        price = int(value)
    except (TypeError, ValueError) as exc:
        raise CoupangCandidateValidationError(f"{field}을(를) 확인하지 못했습니다.") from exc
    if price <= 0:
        raise CoupangCandidateValidationError(f"{field}은(는) 0원보다 커야 합니다.")
    return price


def _https_host(url: str, field: str) -> str:
    parsed = urlparse(_clean(url, field, 2000))
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise CoupangCandidateValidationError(f"{field}은(는) https URL이어야 합니다.")
    return host


def _matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def validate_coupang_candidate(candidate: CoupangCandidate) -> None:
    _clean(candidate.product_id, "쿠팡 상품 ID", 200)
    _clean(candidate.product_name, "상품명")
    _clean(candidate.composition, "구성", 300)

    product_host = _https_host(candidate.product_url, "쿠팡 상품 URL")
    if not _matches_suffix(product_host, COUPANG_PRODUCT_HOST_SUFFIXES):
        raise CoupangCandidateValidationError("쿠팡 상품 URL 도메인을 확인하지 못했습니다.")

    affiliate_host = _https_host(candidate.affiliate_url, "쿠팡 파트너스 링크")
    if affiliate_host not in COUPANG_AFFILIATE_HOSTS:
        raise CoupangCandidateValidationError("검증된 쿠팡 파트너스 단축 링크가 아닙니다.")

    image_host = _https_host(candidate.original_image_url, "원본 대표 이미지 URL")
    if not _matches_suffix(image_host, COUPANG_IMAGE_HOST_SUFFIXES):
        raise CoupangCandidateValidationError("쿠팡 CDN 원본 대표 이미지만 사용할 수 있습니다.")
    if not candidate.source_image_verified:
        raise CoupangCandidateValidationError("원본 대표 이미지 검증이 완료되지 않았습니다.")

    current_price = _positive_price(candidate.current_price or candidate.conditional_price or candidate.sale_price or candidate.normal_price, "현재 구매가")
    if candidate.normal_price is not None:
        _positive_price(candidate.normal_price, "정상가")
    if candidate.sale_price is not None:
        _positive_price(candidate.sale_price, "일반 할인가")
    if candidate.conditional_price is not None:
        _positive_price(candidate.conditional_price, "조건부 가격")
    if candidate.price_condition:
        _clean(candidate.price_condition, "할인 조건", 300)


def build_coupang_approval_draft(candidate: CoupangCandidate) -> dict[str, object]:
    """Build an approval-only Coupang draft; it never claims or publishes a post."""
    validate_coupang_candidate(candidate)
    try:
        content = build_coupang_post(
            Product(
                platform="coupang",
                product_id=_clean(candidate.product_id, "쿠팡 상품 ID", 200),
                name=_clean(candidate.product_name, "상품명"),
                composition=_clean(candidate.composition, "구성", 300),
                image_path=_clean(candidate.original_image_url, "원본 대표 이미지 URL", 2000),
                image_paths=tuple(candidate.original_image_urls or (candidate.original_image_url,)),
                affiliate_url=_clean(candidate.affiliate_url, "쿠팡 파트너스 링크", 2000),
                normal_price=candidate.normal_price,
                sale_price=candidate.sale_price,
                conditional_price=candidate.current_price or candidate.conditional_price or candidate.sale_price or candidate.normal_price,
                price_condition=" ".join(str(candidate.price_condition or "").split()),
            )
        )
    except ContentValidationError as exc:
        raise CoupangCandidateValidationError(str(exc)) from exc

    return {
        "platform": "coupang",
        "product_id": _clean(candidate.product_id, "쿠팡 상품 ID", 200),
        "product_url": _clean(candidate.product_url, "쿠팡 상품 URL", 2000),
        "affiliate_url": _clean(candidate.affiliate_url, "쿠팡 파트너스 링크", 2000),
        "original_image_url": _clean(candidate.original_image_url, "원본 대표 이미지 URL", 2000),
        "original_image_urls": list(candidate.original_image_urls or (candidate.original_image_url,)),
        "draft": content,
        "category_no": 42,
        "naver_write_url": "https://blog.naver.com/GoBlogWrite.naver?categoryNo=42",
        "approval_only": True,
    }
