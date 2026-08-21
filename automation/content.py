from __future__ import annotations

from dataclasses import dataclass
import re

TOSS_DISCLOSURE = "이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
COUPANG_DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
CONDITIONAL_PRICE_NOTICE = (
    "※ 표시된 최저가는 쿠폰 또는 회원 혜택 적용 시의 조건부 가격입니다. "
    "회원 여부, 쿠폰 보유, 선택 옵션과 판매 상황에 따라 최종 결제 가격이 달라질 수 있습니다."
)


class ContentValidationError(ValueError):
    """A product record is insufficiently verified to compose a publishable post."""


@dataclass(frozen=True)
class Product:
    platform: str
    product_id: str
    name: str
    composition: str
    image_path: str
    affiliate_url: str
    price: int | None = None
    normal_price: int | None = None
    sale_price: int | None = None
    conditional_price: int | None = None
    price_condition: str = ""
    description: str = ""
    features: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()


def _text(value: str, label: str, maximum: int = 500) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise ContentValidationError(f"{label}을(를) 확인하지 못했습니다.")
    if len(cleaned) > maximum:
        raise ContentValidationError(f"{label}이(가) 너무 깁니다.")
    return cleaned


def _price(value: int | None, label: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ContentValidationError(f"{label}을(를) 확인하지 못했습니다.") from exc
    if parsed <= 0:
        raise ContentValidationError(f"{label}은(는) 0원보다 커야 합니다.")
    return parsed


def _image_path(product: Product) -> str:
    path = _text(product.image_path, "원본 대표 이미지", 2000)
    if not re.search(r"\.(?:jpe?g|png|webp|gif)(?:$|[?#])", path, re.IGNORECASE):
        raise ContentValidationError("원본 대표 이미지 파일 형식을 확인하지 못했습니다.")
    return path


def _tags(name: str, fixed: tuple[str, ...], minimum: int = 5, maximum: int = 7) -> list[str]:
    tags: list[str] = []
    for token in re.findall(r"[가-힣A-Za-z0-9]+", name):
        token = token.strip()
        if len(token) >= 2 and token not in tags:
            tags.append(token)
        if len(tags) >= maximum - len(fixed):
            break
    for tag in fixed:
        if tag not in tags:
            tags.append(tag)
    generic = ("상품추천", "쇼핑추천", "할인정보", "특가정보", "실속구매")
    for tag in generic:
        if len(tags) >= minimum:
            break
        if tag not in tags:
            tags.append(tag)
    return tags[:maximum]


def _require_product_common(product: Product, expected_platform: str) -> tuple[str, str, str, str, str]:
    if product.platform != expected_platform:
        raise ContentValidationError(f"{expected_platform} 상품만 작성할 수 있습니다.")
    return (
        _text(product.product_id, "상품 ID", 200),
        _text(product.name, "상품명"),
        _text(product.composition, "구성", 300),
        _image_path(product),
        _text(product.affiliate_url, "제휴 URL", 2000),
    )


def build_toss_post(product: Product) -> dict[str, object]:
    _, name, composition, image_path, affiliate_url = _require_product_common(product, "toss")
    price = _price(product.price, "확인 가격")
    title = f"{name}, {composition}, {price:,}원"
    body = "\n\n".join((
        "상품 자세히 보기",
        affiliate_url,
        TOSS_DISCLOSURE,
    ))
    return {
        "title": title,
        "body": body,
        "tags": _tags(name, ("토스쇼핑",)),
        "image_path": image_path,
        "expected_url": affiliate_url,
        "price": price,
        "category_no": 39,
        "category_name": "개이득 토스쇼핑",
    }


def _three(values: tuple[str, ...], fallback_label: str) -> tuple[str, str, str]:
    normalized = tuple(_text(value, fallback_label, 180) for value in values if str(value).strip())
    if len(normalized) < 3:
        raise ContentValidationError(f"{fallback_label} 3개를 확인하지 못했습니다.")
    return normalized[:3]


def build_coupang_post(product: Product) -> dict[str, object]:
    _, name, composition, image_path, affiliate_url = _require_product_common(product, "coupang")
    conditional_price = _price(product.conditional_price or product.sale_price or product.price, "현재 구매가")
    condition = " ".join(str(product.price_condition or "").split())
    condition_text = condition if condition.endswith("적용 시") else (f"{condition} 적용 시" if condition else "")
    title = f"[{name}] {conditional_price:,}원"
    tags = _tags(name, ("골드박스", "쿠팡파트너스"))
    hashtag_line = " ".join(f"#{tag}" for tag in tags)
    body = "\n\n".join((
        f"실제 할인 조건: {condition_text} 최저 구매가 {conditional_price:,}원".replace(":  최저", ": 최저").strip(),
        f"구성: {composition}",
        "상품 자세히 보기",
        affiliate_url,
        COUPANG_DISCLOSURE,
    ))
    return {
        "title": title,
        "body": body,
        "tags": hashtag_line,
        "image_path": image_path,
        "image_paths": list(product.image_paths or (image_path,)),
        "expected_url": affiliate_url,
        "current_price": conditional_price,
        "conditional_price": conditional_price,
        "price_condition": condition,
        "category_no": 42,
        "category_name": "개이득 쿠팡쇼핑",
    }


def build_threads_post(product: Product, source_post: dict[str, object]) -> dict[str, object]:
    platform = _text(str(source_post.get("platform") or ""), "원본 플랫폼", 20).lower()
    naver_url = _text(str(source_post.get("naver_post_url") or ""), "네이버 공개 글 URL", 2000)
    if source_post.get("status") != "PUBLISHED":
        raise ContentValidationError("네이버에 정상 발행된 동일 상품만 Threads에 게시할 수 있습니다.")
    _image_path(product)
    if platform == "toss":
        price = _price(product.price, "확인 가격")
        benefit = f"확인 가격 {price:,}원"
        notice = "가격과 재고는 판매 상황에 따라 달라질 수 있습니다."
        disclosure = TOSS_DISCLOSURE
    elif platform == "coupang":
        price = _price(product.conditional_price, "최저 조건부 가격")
        benefit = f"{_text(product.price_condition, '실제 할인 조건', 300)} 적용 시 {price:,}원"
        notice = CONDITIONAL_PRICE_NOTICE
        disclosure = COUPANG_DISCLOSURE
    else:
        raise ContentValidationError("토스 또는 쿠팡의 네이버 공개 글만 Threads에 게시할 수 있습니다.")
    text = "\n".join((
        product.name,
        benefit,
        notice,
        "상품 보기",
        product.affiliate_url,
        disclosure,
        "#쇼핑정보 #상품추천",
    ))
    if len(text) > 300:
        raise ContentValidationError("Threads 게시문이 300자를 초과했습니다.")
    return {
        "text": text,
        "image_path": _image_path(product),
        "expected_url": product.affiliate_url,
        "naver_post_url": naver_url,
    }
