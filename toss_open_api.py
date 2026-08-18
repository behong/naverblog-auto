from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


OPEN_API_ENV = os.getenv("TOSS_OPEN_API_ENV", "production").strip().lower()
OPEN_API_BASE_URL = os.getenv(
    "TOSS_OPEN_API_BASE_URL",
    "https://alpha-sharelink.toss.im/openapi"
    if OPEN_API_ENV in {"alpha", "test", "testing"}
    else "https://sharelink.toss.im/openapi",
).rstrip("/")
OPEN_API_TOKEN_URL = os.getenv(
    "TOSS_OPEN_API_TOKEN_URL",
    "https://oauth2-alpha.cert.toss.im/token"
    if OPEN_API_ENV in {"alpha", "test", "testing"}
    else "https://oauth2.cert.toss.im/token",
)
OPEN_API_ACCESS_KEY = os.getenv("TOSS_OPEN_API_ACCESS_KEY", "").strip()
OPEN_API_SECRET_KEY = os.getenv("TOSS_OPEN_API_SECRET_KEY", "").strip()
OPEN_API_TOKEN_STORE_FILE = os.getenv("TOSS_OPEN_API_TOKEN_STORE_FILE", "").strip()
OPEN_API_REFRESH_MARGIN_SECONDS = int(
    os.getenv("TOSS_OPEN_API_TOKEN_REFRESH_MARGIN_SECONDS", "300")
)
OPEN_API_TIMEOUT_SECONDS = int(os.getenv("TOSS_OPEN_API_TIMEOUT_SECONDS", "30"))
OPEN_API_MAX_RETRIES = int(os.getenv("TOSS_OPEN_API_MAX_RETRIES", "3"))
TOKEN_SCOPE = "sharelink:read"
MAX_RESPONSE_BYTES = 3 * 1024 * 1024

_token_lock = threading.RLock()
_memory_token: dict[str, Any] = {}


class TossOpenApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def configured() -> bool:
    return bool(OPEN_API_ACCESS_KEY and OPEN_API_SECRET_KEY)


def health() -> dict[str, object]:
    result: dict[str, object] = {
        "status": "error",
        "environment": OPEN_API_ENV,
        "configured": configured(),
    }
    if OPEN_API_ENV != "production":
        result["error"] = "production environment is required"
        return result
    if not configured():
        result["error"] = "credentials are not configured"
        return result
    try:
        get_access_token()
    except TossOpenApiError as exc:
        result["error"] = str(exc)
        return result
    result["status"] = "ok"
    return result


def _credential_hash() -> str:
    return hashlib.sha256(OPEN_API_ACCESS_KEY.encode("utf-8")).hexdigest()[:16]


def _token_store_path() -> Path | None:
    return Path(OPEN_API_TOKEN_STORE_FILE) if OPEN_API_TOKEN_STORE_FILE else None


def _usable_token(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("environment") != OPEN_API_ENV:
        return ""
    if payload.get("credentialKeyHash") != _credential_hash():
        return ""
    token = str(payload.get("accessToken") or "").strip()
    try:
        expires_at = float(payload.get("expiresAt") or 0)
    except (TypeError, ValueError):
        return ""
    if token and expires_at > time.time() + max(OPEN_API_REFRESH_MARGIN_SECONDS, 0):
        return token
    return ""


def _load_cached_token() -> str:
    token = _usable_token(_memory_token)
    if token:
        return token
    path = _token_store_path()
    if path is None:
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return ""
    token = _usable_token(payload)
    if token and isinstance(payload, dict):
        _memory_token.clear()
        _memory_token.update(payload)
    return token


def _save_cached_token(token: str, expires_in: int) -> None:
    payload = {
        "accessToken": token,
        "expiresAt": time.time() + max(expires_in, 1),
        "environment": OPEN_API_ENV,
        "credentialKeyHash": _credential_hash(),
    }
    _memory_token.clear()
    _memory_token.update(payload)
    path = _token_store_path()
    if path is None:
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)
    except OSError:
        # The in-memory cache remains usable when a read-only filesystem blocks persistence.
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _json_body(response: Any) -> dict[str, Any]:
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise TossOpenApiError("토스 Open API 응답이 너무 큽니다.")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TossOpenApiError("토스 Open API 응답 형식을 읽을 수 없습니다.") from exc
    if not isinstance(payload, dict):
        raise TossOpenApiError("토스 Open API 응답 형식이 올바르지 않습니다.")
    return payload


def _issue_access_token() -> str:
    if not configured():
        raise TossOpenApiError("토스 Open API 인증정보가 설정되지 않았습니다.")
    request = urllib.request.Request(
        OPEN_API_TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": OPEN_API_ACCESS_KEY,
                "client_secret": OPEN_API_SECRET_KEY,
                "scope": TOKEN_SCOPE,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(OPEN_API_TIMEOUT_SECONDS, 1)) as response:
            payload = _json_body(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = _json_body(exc)
            reason = str(payload.get("error_description") or payload.get("error") or "")
        except TossOpenApiError:
            reason = ""
        raise TossOpenApiError(reason or "토스 Open API 인증에 실패했습니다.", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TossOpenApiError("토스 Open API 인증 서버에 연결하지 못했습니다.") from exc

    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise TossOpenApiError("토스 Open API 토큰이 응답에 없습니다.")
    try:
        expires_in = int(payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 1
    _save_cached_token(token, expires_in)
    return token


def get_access_token(force_refresh: bool = False) -> str:
    with _token_lock:
        if not force_refresh:
            token = _load_cached_token()
            if token:
                return token
        return _issue_access_token()


def _api_error(payload: object, status: int) -> TossOpenApiError:
    error = payload.get("error") if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    code = str(error.get("errorCode") or "").strip()
    reason = str(error.get("reason") or "").strip()
    try:
        error_status = int(error.get("errorType") or status)
    except (TypeError, ValueError):
        error_status = status
    return TossOpenApiError(
        reason or code or f"토스 Open API 요청에 실패했습니다. ({status})",
        status=error_status,
        code=code,
    )


def _retry_delay(headers: Any, attempt: int) -> float:
    retry_after = str(headers.get("Retry-After") or "").strip() if headers else ""
    try:
        return max(0.0, min(float(retry_after), 30.0)) if retry_after else float(2**attempt)
    except ValueError:
        return float(2**attempt)


def api_request(
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> object:
    max_attempts = max(OPEN_API_MAX_RETRIES, 1)
    refreshed = False
    token = get_access_token()
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        query = urllib.parse.urlencode(params or {})
        url = f"{OPEN_API_BASE_URL}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method=method.upper(),
        )
        status = 0
        headers: Any = None
        try:
            with urllib.request.urlopen(request, timeout=max(OPEN_API_TIMEOUT_SECONDS, 1)) as response:
                status = response.status
                headers = response.headers
                payload = _json_body(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            headers = exc.headers
            try:
                payload = _json_body(exc)
            except TossOpenApiError:
                payload = {}
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < max_attempts:
                time.sleep(float(min(2 ** (attempt - 1), 30)))
                continue
            raise TossOpenApiError("토스 Open API 서버에 연결하지 못했습니다.") from exc

        if 200 <= status < 300 and payload.get("resultType") == "SUCCESS":
            return payload.get("success")
        error = _api_error(payload, status)
        if (error.status == 401 or error.code == "UNAUTHORIZED") and not refreshed:
            refreshed = True
            token = get_access_token(force_refresh=True)
            max_attempts = max(max_attempts, attempt + 1)
            continue
        retryable = error.status in {429, 500} or error.code in {"TOO_MANY_REQUEST", "INTERNAL_ERROR"}
        if retryable and attempt < max_attempts:
            time.sleep(_retry_delay(headers, attempt - 1))
            continue
        raise error
    raise TossOpenApiError("토스 Open API 요청에 실패했습니다.")


def normalize_product(item: dict[str, object]) -> dict[str, object]:
    main_images = item.get("mainImageUrls")
    images = [str(url) for url in main_images if url] if isinstance(main_images, list) else []
    thumbnail = str(item.get("thumbnailUrl") or "").strip()
    if not images and thumbnail:
        images.append(thumbnail)
    price = "".join(character for character in str(item.get("displayPrice") or "") if character.isdigit())
    return {
        "taca_item_id": str(item.get("tacaItemId") or ""),
        "title": str(item.get("displayName") or "").strip(),
        "price": price,
        "images": images,
        "is_sold_out": bool(item.get("isSoldOut")),
    }


def product_detail(taca_item_id: str = "", taca_id: str = "") -> dict[str, object]:
    if not taca_item_id and not taca_id:
        raise TossOpenApiError("토스 상품 ID를 찾지 못했습니다.")
    params = {"tacaItemIds": taca_item_id} if taca_item_id else {"tacaIds": taca_id}
    payload = api_request("GET", "/products/detail", params=params)
    if not isinstance(payload, dict):
        raise TossOpenApiError("토스 상품 상세 응답 형식이 올바르지 않습니다.")
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    selected = next(
        (item for item in items if str(item.get("tacaItemId") or "") == taca_item_id),
        items[0] if items else None,
    )
    if selected is None:
        raise TossOpenApiError("토스 Open API에서 상품 상세 정보를 찾지 못했습니다.")
    return normalize_product(selected)
