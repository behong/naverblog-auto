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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from automation_store import (
    authorized as automation_authorized,
    check_duplicate,
    configured as automation_configured,
    health as automation_health,
    init_schema as init_automation_schema,
    recent_runs,
    recent_toss_products,
    upsert_post,
    upsert_run,
)
from toss_collector import collect_toss_listing
from toss_open_api import (
    TossOpenApiError,
    configured as open_api_configured,
    health as open_api_health,
    product_detail,
)


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
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
        if parsed.path == "/api/image":
            self._handle_image(parsed)
            return

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
        self._send_bytes(file_path.read_bytes(), content_type)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
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
        server.server_close()


if __name__ == "__main__":
    main()
