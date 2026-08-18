from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass


_HASH_PREFIX = "pbkdf2_sha256"
_HASH_ITERATIONS = 600_000
_SESSION_TTL_SECONDS = max(300, int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "28800")))
_LOGIN_WINDOW_SECONDS = max(60, int(os.getenv("ADMIN_LOGIN_WINDOW_SECONDS", "900")))
_LOGIN_MAX_ATTEMPTS = max(1, int(os.getenv("ADMIN_LOGIN_MAX_ATTEMPTS", "5")))
_LOGIN_LOCK_SECONDS = max(60, int(os.getenv("ADMIN_LOGIN_LOCK_SECONDS", "900")))
_ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()


@dataclass(frozen=True)
class AdminSession:
    csrf_token: str
    expires_at: float


_lock = threading.RLock()
_sessions: dict[str, AdminSession] = {}
_attempts: dict[str, list[float]] = {}
_lockouts: dict[str, float] = {}


def configured(password_hash: str | None = None) -> bool:
    return bool((password_hash if password_hash is not None else _ADMIN_PASSWORD_HASH).strip())


def create_password_hash(password: str) -> str:
    """Create a portable PBKDF2-SHA256 value for ADMIN_PASSWORD_HASH."""
    if len(password) < 12:
        raise ValueError("관리자 비밀번호는 12자 이상으로 설정해 주세요.")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_hash = base64.urlsafe_b64encode(derived).decode("ascii").rstrip("=")
    return f"{_HASH_PREFIX}${_HASH_ITERATIONS}${encoded_salt}${encoded_hash}"


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def verify_password(password: str, password_hash: str | None = None) -> bool:
    configured_hash = (password_hash if password_hash is not None else _ADMIN_PASSWORD_HASH).strip()
    if not configured(configured_hash) or not password:
        return False
    try:
        algorithm, raw_iterations, encoded_salt, encoded_hash = configured_hash.split("$", 3)
        iterations = int(raw_iterations)
        if algorithm != _HASH_PREFIX or iterations < 100_000:
            return False
        expected = _decode(encoded_hash)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _decode(encoded_salt), iterations
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _purge(now: float) -> None:
    expired_sessions = [token for token, session in _sessions.items() if session.expires_at <= now]
    for token in expired_sessions:
        _sessions.pop(token, None)
    for address, attempts in list(_attempts.items()):
        recent = [attempt for attempt in attempts if attempt > now - _LOGIN_WINDOW_SECONDS]
        if recent:
            _attempts[address] = recent
        else:
            _attempts.pop(address, None)
    for address, expires_at in list(_lockouts.items()):
        if expires_at <= now:
            _lockouts.pop(address, None)


def login_allowed(address: str) -> bool:
    with _lock:
        now = time.time()
        _purge(now)
        return _lockouts.get(address, 0) <= now


def record_failed_login(address: str) -> None:
    with _lock:
        now = time.time()
        _purge(now)
        attempts = _attempts.setdefault(address, [])
        attempts.append(now)
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            _lockouts[address] = now + _LOGIN_LOCK_SECONDS
            _attempts.pop(address, None)


def create_session() -> tuple[str, AdminSession]:
    with _lock:
        now = time.time()
        _purge(now)
        raw_token = secrets.token_urlsafe(32)
        stored_token = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
        session = AdminSession(csrf_token=secrets.token_urlsafe(24), expires_at=now + _SESSION_TTL_SECONDS)
        _sessions[stored_token] = session
        return raw_token, session


def session_for(raw_token: str | None) -> AdminSession | None:
    if not raw_token:
        return None
    with _lock:
        now = time.time()
        _purge(now)
        return _sessions.get(hashlib.sha256(raw_token.encode("ascii", errors="ignore")).hexdigest())


def revoke_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    with _lock:
        _sessions.pop(hashlib.sha256(raw_token.encode("ascii", errors="ignore")).hexdigest(), None)


def csrf_valid(session: AdminSession | None, submitted_token: str | None) -> bool:
    return bool(session and submitted_token and hmac.compare_digest(session.csrf_token, submitted_token))



def revoke_all_sessions() -> None:
    with _lock:
        _sessions.clear()
