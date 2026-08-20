from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import random
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html import escape, unescape
from html.parser import HTMLParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from admin_auth import (
    AdminSession,
    create_password_hash,
    create_session,
    csrf_valid,
    login_allowed,
    record_failed_login,
    revoke_all_sessions,
    revoke_session,
    session_for,
    verify_password,
)
from automation_store import (
    admin_password_hash,
    begin_extension_publish,
    admin_toss_publisher_id,
    admin_toss_publisher_settings,
    authorized as automation_authorized,
    check_duplicate,
    latest_unclaimed_approved_publication,
    mark_publication_approval_claimed,
    record_extension_pre_publish_failure,
    record_extension_preflight_success,
    record_extension_publish_result,
    configured as automation_configured,
    create_extension_device,
    extension_device_valid,
    health as automation_health,
    init_schema as init_automation_schema,
    recent_runs,
    recent_toss_products,
    set_admin_password_hash,
    set_admin_toss_publisher_id,
    toss_product_with_share_link,
    upsert_post,
    upsert_run,
)
from toss_collector import collect_toss_listing, issue_toss_share_link
from coupang_publication import (
    approved_coupang_draft,
    begin_coupang_extension_publish,
    claim_coupang_approval,
    record_coupang_pre_publish_failure,
    record_coupang_publish_result,
    request_coupang_publication_approval,
)
from toss_open_api import (
    TossOpenApiError,
    configured as open_api_configured,
    health as open_api_health,
    product_detail,
)
from telegram_approval import configured as telegram_approval_configured, start_polling


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
APP_PUBLIC_ORIGIN = os.getenv("PUBLIC_BASE_URL", "https://blogauto.hongzi.us").rstrip("/")
HOST = os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("APP_PORT", "8765"))
OPEN_BROWSER = os.getenv("APP_OPEN_BROWSER", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
TOSS_IMAGE_HOSTS = {"shopping.toss.im", "resources-fe.toss.im", "static.toss.im"}
COUPANG_IMAGE_HOSTS = {"coupangcdn.com"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)
DISCLOSURE = (
    "✱ 이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, "
    "이에 따른 일정액의 수수료를 제공받습니다."
)


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() != "meta":
            return
        key = (values.get("property") or values.get("name") or "").lower()
        content = values.get("content", "").strip()
        if key and content and key not in self.meta:
            self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def build_admin_toss_draft(taca_item_id: str) -> dict[str, object]:
    item_id = str(taca_item_id or "").strip()
    stored = toss_product_with_share_link(item_id)
    if not stored:
        raise ValueError("수집된 토스 상품을 찾지 못했습니다.")
    if bool(stored.get("is_sold_out")):
        raise ValueError("품절 상품은 블로그 초안을 만들 수 없습니다.")
    if check_duplicate("toss", item_id).get("exists"):
        raise ValueError("이미 처리 이력이 있는 상품은 중복 발행할 수 없습니다.")
    share_url = str(stored.get("short_url") or "").strip()
    if not share_url.startswith("https://"):
        raise ValueError("검증된 토스 쉐어링크가 없습니다.")
    detail = product_detail(taca_item_id=item_id)
    if bool(detail.get("is_sold_out")):
        raise ValueError("토스에서 현재 품절로 확인되어 초안 준비를 중단했습니다.")
    images = detail.get("images") if isinstance(detail.get("images"), list) else []
    image_url = str(images[0] or "").strip() if images else ""
    if not image_url.startswith("https://"):
        raise ValueError("원본 대표 이미지를 확인하지 못해 초안 준비를 중단했습니다.")
    try:
        price = int(str(detail.get("price") or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("현재 가격을 확인하지 못해 초안 준비를 중단했습니다.") from exc
    if price <= 0:
        raise ValueError("현재 가격이 올바르지 않아 초안 준비를 중단했습니다.")
    title = " ".join(str(detail.get("title") or stored.get("product_name") or "").split())
    if not title:
        raise ValueError("상품명을 확인하지 못했습니다.")
    recommendation = random.choice((
        "필요했던 생활용품이라면 구성과 현재 가격을 함께 확인해 보세요.",
        "실속 있게 준비하기 좋은 구성인지 살펴보세요.",
        "할인 중일 때 미리 준비해 두기 좋은 상품이에요.",
        "구성과 현재 판매 조건을 확인한 뒤 선택해 보세요.",
    ))
    tag_tokens = []
    for token in re.findall(r"[가-힣A-Za-z0-9]+", title):
        if len(token) >= 2 and token not in tag_tokens:
            tag_tokens.append(token)
        if len(tag_tokens) >= 5:
            break
    for token in ("토스쇼핑", "쇼핑추천", "특가정보"):
        if token not in tag_tokens:
            tag_tokens.append(token)
    tags = " ".join(f"#{token}" for token in tag_tokens[:7])
    return {
        "product_id": item_id,
        "product_name": title,
        "price": price,
        "affiliate_url": share_url,
        "draft": {
            "title": f"{title}, {price:,}원",
            "body": "\n\n".join(("상품 자세히 보기", share_url, recommendation, DISCLOSURE)),
            "tags": tags,
            "imageUrl": f"{APP_PUBLIC_ORIGIN}/api/image?url={urllib.parse.quote(image_url, safe='')}",
        },
        "category_no": 39,
        "naver_write_url": "https://blog.naver.com/GoBlogWrite.naver?categoryNo=39",
    }


def parse_pasted_text(raw: str) -> dict[str, str]:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    url_match = re.search(r"https?://[^\s]+", normalized)
    share_url = url_match.group(0).rstrip(".,)") if url_match else ""
    price_matches = re.findall(r"(?<!\d)(\d[\d,]*)\s*원", normalized)
    price = price_matches[-1].replace(",", "") if price_matches else ""

    product_lines: list[str] = []
    for original_line in normalized.split("\n"):
        line = original_line.strip()
        if not line or re.search(r"https?://", line):
            continue
        if "토스쇼핑 쉐어링크 활동의 일환" in line:
            continue
        if line in {"✱", "*"}:
            continue
        if re.fullmatch(r"\d[\d,]*\s*원?", line):
            continue
        product_lines.append(line)

    product_name = max(product_lines, key=len) if product_lines else ""
    product_name = re.sub(r"\s*,?\s*\d[\d,]*\s*원\s*$", "", product_name).strip(" ,")
    return {
        "raw": normalized,
        "product_name": product_name,
        "share_url": share_url,
        "price": price,
    }


def _validate_remote_url(url: str, allowed_hosts: set[str]) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("https 링크만 사용할 수 있습니다.")

    hostname = parsed.hostname.lower().rstrip(".")
    if not any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts):
        raise ValueError("토스쇼핑 링크만 사용할 수 있습니다.")

    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("링크 주소를 찾을 수 없습니다.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("안전하지 않은 주소는 열 수 없습니다.")
    return parsed


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_remote_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote(url: str, allowed_hosts: set[str], max_bytes: int) -> tuple[bytes, str, str]:
    _validate_remote_url(url, allowed_hosts)
    opener = urllib.request.build_opener(SafeRedirectHandler(allowed_hosts))
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        },
    )
    with opener.open(request, timeout=15) as response:
        final_url = response.geturl()
        _validate_remote_url(final_url, allowed_hosts)
        content_type = response.headers.get_content_type()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("가져오려는 파일이 너무 큽니다.")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("가져오려는 파일이 너무 큽니다.")
        return data, final_url, content_type


def fetch_product_metadata(url: str) -> dict[str, object]:
    data, final_url, content_type = _open_remote(
        url, {"toss.im", "toss.shopping"}, MAX_PAGE_BYTES
    )
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("상품 페이지 형식을 읽을 수 없습니다.")

    html_text = data.decode("utf-8", errors="replace")
    parser = MetadataParser()
    parser.feed(html_text)

    title = parser.meta.get("og:title") or parser.title
    title = re.sub(r"\s*[|｜-]\s*토스쇼핑\s*$", "", unescape(title)).strip()
    description = unescape(parser.meta.get("og:description", "")).strip()
    image_url = unescape(parser.meta.get("og:image", "")).strip()
    images = [image_url] if image_url.startswith("https://") else []
    item_id_match = re.search(r"tacaItemId[^0-9]{1,16}(\d+)", html_text)
    taca_item_id = item_id_match.group(1) if item_id_match else ""
    taca_id_match = re.search(r"/t/(\d+)", urllib.parse.urlparse(final_url).path)
    taca_id = taca_id_match.group(1) if taca_id_match else ""

    return {
        "final_url": final_url,
        "title": title,
        "description": description,
        "images": images,
        "taca_item_id": taca_item_id,
        "taca_id": taca_id,
    }


def _build_tags(name: str) -> list[str]:
    tags: list[str] = []

    def strip_particle(value: str) -> str:
        particles = ("으로", "에서", "에게", "까지", "부터", "처럼", "보다", "에는", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도")
        for particle in particles:
            if value.endswith(particle) and len(value) - len(particle) >= 2:
                return value[: -len(particle)]
        return value

    def add(value: str) -> None:
        cleaned = strip_particle(re.sub(r"[^가-힣A-Za-z0-9]", "", value))
        if len(cleaned) >= 2 and cleaned not in tags:
            tags.append(cleaned)

    tokens = re.findall(r"[가-힣A-Za-z]+", name)
    stopwords = {"고소한", "넣은", "있는", "위한", "제품", "세트"}
    for token in tokens:
        if token not in stopwords and len(token) >= 2:
            add(token)

    for tag in ("상품추천", "쇼핑추천", "실속구매"):
        add(tag)
    add("토스쇼핑")
    return tags[:10]


def _recommendation_line(product_name: str, clean_price: str) -> str:
    name = product_name.rstrip(" ,")
    choices = (
        "구성과 현재 판매 가격을 함께 비교해 본 뒤 선택해 보세요.",
        f"{int(clean_price):,}원 기준으로 필요한 구성인지 살펴보면 좋겠습니다.",
        "필요한 분량인지와 판매 조건을 확인한 뒤 선택해 보세요.",
        "구매 전 상품 상세의 구성과 옵션을 한 번 더 확인해 보면 좋겠습니다.",
    )
    return random.choice(choices)


def generate_post(product_name: str, share_url: str, price: str) -> dict[str, object]:
    clean_price = re.sub(r"\D", "", price)
    if not clean_price:
        raise ValueError("가격을 숫자로 입력해 주세요.")
    title = f"{product_name.rstrip(' ,')}, {clean_price}원"
    body_lines = [
        "[이미지 영역]",
        "",
        "상품 자세히 보기",
        share_url,
        "",
        _recommendation_line(product_name, clean_price),
        "",
        DISCLOSURE,
    ]
    tags = _build_tags(product_name)
    return {"title": title, "body": "\n".join(body_lines), "tags": tags}


def analyze(raw: str, supplied_price: str = "") -> dict[str, object]:
    parsed = parse_pasted_text(raw)
    if not parsed["share_url"]:
        raise ValueError("토스 쉐어링크를 함께 붙여넣어 주세요.")

    metadata: dict[str, object] = {
        "title": "",
        "description": "",
        "images": [],
        "final_url": "",
        "taca_item_id": "",
        "taca_id": "",
        "price": "",
        "price_source": "",
        "data_source": "page",
    }
    warnings: list[str] = []
    try:
        metadata = fetch_product_metadata(parsed["share_url"])
    except (ValueError, urllib.error.URLError, TimeoutError) as exc:
        warnings.append(f"상품 페이지 정보를 가져오지 못했습니다: {exc}")

    if open_api_configured() and (metadata.get("taca_item_id") or metadata.get("taca_id")):
        try:
            official = product_detail(
                str(metadata.get("taca_item_id") or ""),
                str(metadata.get("taca_id") or ""),
            )
            official_images = official.get("images")
            if isinstance(official_images, list) and official_images:
                metadata["images"] = official_images
            if official.get("title"):
                metadata["official_title"] = official["title"]
            if official.get("taca_item_id"):
                metadata["taca_item_id"] = official["taca_item_id"]
            if official.get("price"):
                metadata["price"] = official["price"]
                metadata["price_source"] = "toss-open-api"
            metadata["data_source"] = "toss-open-api"
            metadata["is_sold_out"] = bool(official.get("is_sold_out"))
            if metadata["is_sold_out"]:
                warnings.append("현재 품절로 표시된 상품입니다. 발행 전에 판매 상태를 확인해 주세요.")
        except TossOpenApiError as exc:
            warnings.append(f"토스 Open API 조회에 실패했습니다: {exc}")

    product_name = (
        parsed["product_name"]
        or str(metadata.get("official_title") or "").strip()
        or str(metadata.get("title") or "").strip()
    )
    if not product_name:
        raise ValueError("상품명을 함께 붙여넣어 주세요.")
    price = re.sub(r"\D", "", supplied_price or parsed["price"])
    if price:
        metadata["price"] = price
        metadata["price_source"] = "input"
    elif metadata.get("price_source") == "toss-open-api":
        price = str(metadata.get("price") or "")
    if not price:
        raise ValueError(
            " ".join(warnings)
            or "토스에서 현재 가격을 자동 조회하지 못했습니다. 가격을 직접 입력해 주세요."
        )

    generated = generate_post(product_name, parsed["share_url"], price)
    return {
        **parsed,
        "product_name": product_name,
        "price": price,
        "metadata": metadata,
        "metadata_warning": " ".join(warnings),
        "generated": generated,
        "disclosure": DISCLOSURE,
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "NaverBlogHelper/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _public_origin(self) -> str:
        configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if configured:
            parsed = urllib.parse.urlparse(configured)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        scheme = forwarded_proto if forwarded_proto in {"http", "https"} else "http"
        forwarded_host = self.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
        host = forwarded_host or self.headers.get("Host", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9.:[\]-]+", host):
            host = f"127.0.0.1:{PORT}"
        return f"{scheme}://{host}"

    def _read_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 1024 * 1024:
            raise ValueError("입력 내용의 크기를 확인해 주세요.")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON 객체를 전송해 주세요.")
        return payload

    def _require_automation_auth(self) -> bool:
        if automation_authorized(self.headers.get("Authorization")):
            return True
        self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return False

    def _request_is_secure(self) -> bool:
        forwarded = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        if forwarded in {"http", "https"}:
            return forwarded == "https"
        configured = os.getenv("PUBLIC_BASE_URL", "").strip().lower()
        return configured.startswith("https://")

    def _admin_password_hash(self) -> str:
        try:
            return admin_password_hash()
        except RuntimeError:
            return ""

    def _admin_cookie_value(self) -> str:
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return str(cookies.get("nba_admin_session").value) if cookies.get("nba_admin_session") else ""
        except (ValueError, TypeError):
            return ""

    def _admin_session(self) -> AdminSession | None:
        return session_for(self._admin_cookie_value())

    def _admin_cookie_header(self, raw_token: str = "", clear: bool = False) -> str:
        cookies = SimpleCookie()
        cookies["nba_admin_session"] = "" if clear else raw_token
        morsel = cookies["nba_admin_session"]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Strict"
        if self._request_is_secure():
            morsel["secure"] = True
        if clear:
            morsel["max-age"] = 0
        return cookies.output(header="").strip()

    def _send_admin_json(
        self,
        payload: object,
        status: int = 200,
        *,
        cookie_token: str = "",
        clear_cookie: bool = False,
    ) -> None:
        headers: dict[str, str] = {"Cache_Control": "no-store"}
        if cookie_token or clear_cookie:
            headers["Set_Cookie"] = self._admin_cookie_header(cookie_token, clear_cookie)
        self._send_json_with_headers(payload, status, headers)

    def _send_json_with_headers(self, payload: object, status: int, headers: dict[str, str]) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status, **headers)

    def _require_admin(self) -> AdminSession | None:
        session = self._admin_session()
        if session:
            return session
        self._send_admin_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return None

    def _require_admin_csrf(self, session: AdminSession) -> bool:
        if csrf_valid(session, self.headers.get("X-CSRF-Token")):
            return True
        self._send_admin_json({"ok": False, "error": "csrf_invalid"}, HTTPStatus.FORBIDDEN)
        return False

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/sitemap.xml":
            origin = escape(self._public_origin(), quote=True)
            sitemap = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"  <url><loc>{origin}/</loc></url>\n"
                "</urlset>\n"
            )
            self._send_bytes(sitemap.encode("utf-8"), "application/xml; charset=utf-8")
            return
        if parsed.path == "/robots.txt":
            robots = (
                "User-agent: *\n"
                "Allow: /\n"
                "Disallow: /internal-toss.html\n"
                "Disallow: /admin/\n"
                f"Sitemap: {self._public_origin()}/sitemap.xml\n"
            )
            self._send_bytes(robots.encode("utf-8"), "text/plain; charset=utf-8")
            return
        if parsed.path == "/health":
            automation = automation_health()
            toss = open_api_health()
            status = (
                "ok"
                if automation.get("database") != "error" and toss.get("status") == "ok"
                else "error"
            )
            self._send_json(
                {
                    "status": status,
                    "service": "naverblog-auto",
                    "automation": automation,
                    "toss_open_api": toss,
                },
                HTTPStatus.OK if status == "ok" else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if parsed.path == "/api/coupang/extension/approved-draft":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                prepared = approved_coupang_draft()
                if not prepared:
                    self._send_json({"ok": True, "result": None})
                    return
                draft = prepared.get("draft") if isinstance(prepared.get("draft"), dict) else {}
                image_url = str(prepared.get("original_image_url") or "").strip()
                if not image_url.startswith("https://"):
                    raise ValueError("검증된 쿠팡 원본 대표 이미지를 확인하지 못했습니다.")
                draft["imageUrl"] = f"{APP_PUBLIC_ORIGIN}/api/coupang/image?url={urllib.parse.quote(image_url, safe='')}"
                prepared["draft"] = draft
                prepared.pop("original_image_url", None)
                self._send_json({"ok": True, "result": prepared})
                return
            except (ValueError, RuntimeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
        if parsed.path == "/api/extension/approved-draft":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                claimed = latest_unclaimed_approved_publication()
                if not claimed:
                    self._send_json({"ok": True, "result": None})
                    return
                summary = claimed.get("summary") if isinstance(claimed.get("summary"), list) else []
                if len(summary) != 1:
                    raise ValueError("단건 승인 배치만 자동 입력할 수 있습니다.")
                item_id = str((summary[0] or {}).get("product_id") or "")
                prepared = build_admin_toss_draft(item_id)
                draft = prepared.get("draft") if isinstance(prepared.get("draft"), dict) else {}
                draft["approvalBatchId"] = str(claimed.get("id") or "")
                draft["preflightOnly"] = str(claimed.get("source") or "") == "toss-preflight"
                product = {
                    "platform": "toss",
                    "product_id": prepared.get("product_id"),
                    "product_name": prepared.get("product_name"),
                    "sale_price": prepared.get("price"),
                    "affiliate_url": prepared.get("affiliate_url"),
                    "naver_category": str(prepared.get("category_no") or ""),
                }
                self._send_json({"ok": True, "result": {"batch_id": str(claimed.get("id") or ""), "draft": draft, "product": product, "preflight_only": bool(draft.get("preflightOnly")), "naver_write_url": prepared.get("naver_write_url")}})
                return
            except (ValueError, RuntimeError, TossOpenApiError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
        if parsed.path.startswith("/api/admin/"):
            if not self._admin_password_hash():
                self._send_admin_json({"ok": False, "error": "admin_not_configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            session = self._require_admin()
            if session is None:
                return
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/admin/session":
                    self._send_admin_json(
                        {"ok": True, "result": {"csrf_token": session.csrf_token, "expires_at": session.expires_at}}
                    )
                    return
                if parsed.path == "/api/admin/settings":
                    publisher = admin_toss_publisher_settings()
                    self._send_admin_json(
                        {
                            "ok": True,
                            "result": {
                                "publisher_configured": bool(publisher["configured"]),
                                "publisher_source": publisher["source"],
                            },
                        }
                    )
                    return
                if parsed.path == "/api/admin/toss/products":
                    source = query.get("source", ["best-selling"])[0]
                    limit = int(query.get("limit", ["30"])[0])
                    self._send_admin_json({"ok": True, "result": recent_toss_products(source, limit)})
                    return
            except (ValueError, RuntimeError) as exc:
                self._send_admin_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/automation/"):
            if not self._require_automation_auth():
                return
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/automation/health":
                    self._send_json({"ok": True, "result": automation_health()})
                    return
                if parsed.path == "/api/automation/posts/check":
                    platform = query.get("platform", [""])[0].strip().lower()
                    product_id = query.get("product_id", [""])[0].strip()
                    self._send_json({"ok": True, "result": check_duplicate(platform, product_id)})
                    return
                if parsed.path == "/api/automation/runs/recent":
                    limit = int(query.get("limit", ["20"])[0])
                    self._send_json({"ok": True, "result": recent_runs(limit)})
                    return
                if parsed.path == "/api/automation/toss/products":
                    source = query.get("source", ["best-selling"])[0]
                    limit = int(query.get("limit", ["30"])[0])
                    self._send_json({"ok": True, "result": recent_toss_products(source, limit)})
                    return
            except (ValueError, RuntimeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/coupang/image":
            self._handle_coupang_image(parsed)
            return
        if parsed.path == "/api/image":
            self._handle_image(parsed)
            return

        if parsed.path in {"/admin", "/admin/"}:
            relative = "admin.html"
        elif parsed.path in {"/admin/setup", "/admin/setup/"}:
            relative = "admin-setup.html"
        else:
            relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()
        try:
            file_path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        cache_headers: dict[str, str] = {}
        if relative in {"admin.html", "admin.js", "admin-setup.html", "admin-setup.js", "internal-toss.css"}:
            cache_headers["Cache_Control"] = "no-store, max-age=0"
        self._send_bytes(file_path.read_bytes(), content_type, **cache_headers)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/coupang/collector/approval":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
                result = request_coupang_publication_approval(candidate, int(payload.get("ttl_minutes") or 30))
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/coupang/extension/publish/begin":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = begin_coupang_extension_publish(
                    str(payload.get("batch_id") or ""),
                    payload.get("product") if isinstance(payload.get("product"), dict) else {},
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/coupang/extension/publish/pre-submit-failure":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = record_coupang_pre_publish_failure(
                    str(payload.get("batch_id") or ""),
                    str(payload.get("error_message") or ""),
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/coupang/extension/publish/preflight-success":
            self._send_json({"ok": False, "error": "coupang_preflight_not_supported"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/coupang/extension/publish/result":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = record_coupang_publish_result(
                    str(payload.get("batch_id") or ""),
                    str(payload.get("publish_token") or ""),
                    str(payload.get("outcome") or ""),
                    str(payload.get("naver_post_url") or ""),
                    str(payload.get("error_message") or ""),
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/coupang/extension/approved-draft/claim":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                claimed = claim_coupang_approval(str(payload.get("batch_id") or ""))
                self._send_json({"ok": True, "result": {"claimed": claimed}})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/extension/publish/begin":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = begin_extension_publish(
                    str(payload.get("batch_id") or ""),
                    payload.get("product") if isinstance(payload.get("product"), dict) else {},
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/extension/publish/pre-submit-failure":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = record_extension_pre_publish_failure(
                    str(payload.get("batch_id") or ""),
                    str(payload.get("error_message") or ""),
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/extension/publish/preflight-success":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = record_extension_preflight_success(str(payload.get("batch_id") or ""))
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/extension/publish/result":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                result = record_extension_publish_result(
                    str(payload.get("batch_id") or ""),
                    str(payload.get("publish_token") or ""),
                    str(payload.get("outcome") or ""),
                    str(payload.get("naver_post_url") or ""),
                    str(payload.get("error_message") or ""),
                )
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/extension/approved-draft/claim":
            device_token = self.headers.get("X-Naver-Draft-Device", "")
            if not extension_device_valid(device_token):
                self._send_json({"ok": False, "error": "extension_unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = self._read_json()
                claimed = mark_publication_approval_claimed(str(payload.get("batch_id") or ""))
                self._send_json({"ok": True, "result": {"claimed": claimed}})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/admin/setup":
            if not self._require_automation_auth():
                return
            try:
                payload = self._read_json()
                password = str(payload.get("password") or "")
                confirmation = str(payload.get("confirmation") or "")
                if password != confirmation:
                    raise ValueError("비밀번호 확인이 일치하지 않습니다.")
                set_admin_password_hash(create_password_hash(password))
                revoke_all_sessions()
                self._send_json({"ok": True, "result": {"configured": True}})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/admin/login":
            configured_hash = self._admin_password_hash()
            if not configured_hash:
                self._send_admin_json({"ok": False, "error": "admin_not_configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            address = str(self.client_address[0] or "unknown")
            if not login_allowed(address):
                self._send_admin_json({"ok": False, "error": "too_many_attempts"}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            try:
                payload = self._read_json()
                password = str(payload.get("password") or "")
            except (ValueError, json.JSONDecodeError):
                self._send_admin_json({"ok": False, "error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return
            if not verify_password(password, configured_hash):
                record_failed_login(address)
                self._send_admin_json({"ok": False, "error": "invalid_credentials"}, HTTPStatus.UNAUTHORIZED)
                return
            raw_token, session = create_session()
            self._send_admin_json(
                {"ok": True, "result": {"csrf_token": session.csrf_token, "expires_at": session.expires_at}},
                cookie_token=raw_token,
            )
            return
        if parsed.path.startswith("/api/admin/"):
            if not self._admin_password_hash():
                self._send_admin_json({"ok": False, "error": "admin_not_configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            session = self._require_admin()
            if session is None:
                return
            if not self._require_admin_csrf(session):
                return
            try:
                payload = self._read_json()
                if parsed.path == "/api/admin/logout":
                    revoke_session(self._admin_cookie_value())
                    self._send_admin_json({"ok": True}, clear_cookie=True)
                    return
                if parsed.path == "/api/admin/extension/pair":
                    self._send_admin_json({"ok": True, "result": {"device_token": create_extension_device()}})
                    return
                if parsed.path == "/api/admin/settings/publisher":
                    publisher_id = str(payload.get("publisher_id") or "").strip()
                    import uuid
                    uuid.UUID(publisher_id)
                    set_admin_toss_publisher_id(publisher_id)
                    publisher = admin_toss_publisher_settings()
                    self._send_admin_json(
                        {
                            "ok": True,
                            "result": {
                                "publisher_configured": bool(publisher["configured"]),
                                "publisher_source": publisher["source"],
                            },
                        }
                    )
                    return
                if parsed.path == "/api/admin/coupang/approvals":
                    result = request_coupang_publication_approval(
                        payload if isinstance(payload, dict) else {},
                        int(payload.get("ttl_minutes") or 30),
                    )
                    self._send_admin_json({"ok": True, "result": result})
                    return
                if parsed.path == "/api/admin/toss/links":
                    result = issue_toss_share_link(str(payload.get("taca_item_id") or ""))
                    self._send_admin_json({"ok": True, "result": result})
                    return
                if parsed.path == "/api/admin/toss/drafts":
                    result = build_admin_toss_draft(str(payload.get("taca_item_id") or ""))
                    self._send_admin_json({"ok": True, "result": result})
                    return
                if parsed.path == "/api/admin/toss/collect":
                    result = collect_toss_listing(
                        str(payload.get("source") or "best-selling"),
                        int(payload.get("size") or 30),
                    )
                    self._send_admin_json({"ok": True, "result": result})
                    return
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_admin_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/automation/"):
            if not self._require_automation_auth():
                return
            try:
                payload = self._read_json()
                if parsed.path == "/api/automation/runs":
                    result = upsert_run(payload)
                elif parsed.path == "/api/automation/posts":
                    result = upsert_post(payload)
                elif parsed.path == "/api/automation/toss/collect":
                    result = collect_toss_listing(
                        str(payload.get("source") or "best-selling"),
                        int(payload.get("size") or 30),
                    )
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "result": result})
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            raw = str(payload.get("text", "")).strip()
            price = str(payload.get("price", "")).strip()
            if not raw:
                raise ValueError("상품명과 링크를 붙여넣어 주세요.")
            self._send_json({"ok": True, "result": analyze(raw, price)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # Keep the local UI usable when a product page changes.
            self._send_json(
                {"ok": False, "error": f"처리 중 오류가 발생했습니다: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_coupang_image(self, parsed: urllib.parse.ParseResult) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        image_url = query.get("url", [""])[0]
        try:
            data, _, content_type = _open_remote(
                image_url,
                COUPANG_IMAGE_HOSTS,
                MAX_IMAGE_BYTES,
            )
            if not content_type.startswith("image/"):
                raise ValueError("이미지 파일이 아닙니다.")
            headers = {"Cache_Control": "private, max-age=3600"}
            self._send_bytes(data, content_type, **headers)
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _handle_image(self, parsed: urllib.parse.ParseResult) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        image_url = query.get("url", [""])[0]
        try:
            data, _, content_type = _open_remote(
                image_url,
                TOSS_IMAGE_HOSTS,
                MAX_IMAGE_BYTES,
            )
            if not content_type.startswith("image/"):
                raise ValueError("이미지 파일이 아닙니다.")
            headers = {"Cache_Control": "private, max-age=3600"}
            if query.get("download") == ["1"]:
                extension = mimetypes.guess_extension(content_type) or ".jpg"
                headers["Content_Disposition"] = f'attachment; filename="toss-product{extension}"'
            self._send_bytes(data, content_type, **headers)
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    if automation_configured():
        init_automation_schema()
    telegram_stop_event = threading.Event()
    telegram_worker = start_polling(telegram_stop_event) if telegram_approval_configured() else None
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    url = f"http://{HOST}:{PORT}"
    print("\n네이버 블로그 글 도우미를 시작했습니다.")
    print(f"브라우저가 열리지 않으면 {url} 로 접속하세요.")
    print("종료하려면 이 창에서 Ctrl+C를 누르세요.\n")
    if OPEN_BROWSER:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        telegram_stop_event.set()
        if telegram_worker:
            telegram_worker.join(timeout=2)
        server.server_close()


if __name__ == "__main__":
    main()
