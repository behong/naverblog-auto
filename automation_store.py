from __future__ import annotations

import csv
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTOMATION_API_TOKEN = os.getenv("AUTOMATION_API_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DB_MAX_RETRIES = max(1, int(os.getenv("DB_MAX_RETRIES", "3")))
AUTOMATION_AUDIT_CSV_PATH = os.getenv(
    "AUTOMATION_AUDIT_CSV_PATH", "data/automation_history.csv"
).strip()

RUN_STATUSES = {
    "STARTED",
    "DISCOVERED",
    "LINK_CREATED",
    "PRICE_VERIFIED",
    "DRAFT_CREATED",
    "AWAITING_APPROVAL",
    "PUBLISHING",
    "PUBLISHED",
    "SKIPPED",
    "FAILED",
    "AUTH_REQUIRED",
    "PRICE_MISMATCH",
    "IMAGE_FAILED",
    "EDITOR_FAILED",
    "PUBLISH_UNKNOWN",
}
POST_STATUSES = {
    "DISCOVERED",
    "LINK_CREATED",
    "PRICE_VERIFIED",
    "DRAFT_CREATED",
    "AWAITING_APPROVAL",
    "PUBLISHING",
    "PUBLISHED",
    "FAILED",
    "SKIPPED",
}
ALERT_STATUSES = {
    "FAILED",
    "AUTH_REQUIRED",
    "PRICE_MISMATCH",
    "IMAGE_FAILED",
    "EDITOR_FAILED",
    "PUBLISH_UNKNOWN",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS automation_runs (
    id uuid PRIMARY KEY,
    job_name text NOT NULL,
    platform text NOT NULL CHECK (platform IN ('toss', 'coupang', 'threads')),
    status text NOT NULL,
    step text NOT NULL DEFAULT '',
    product_id text NOT NULL DEFAULT '',
    product_name text NOT NULL DEFAULT '',
    error_code text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS automation_runs_updated_idx
    ON automation_runs (updated_at DESC);
CREATE INDEX IF NOT EXISTS automation_runs_status_idx
    ON automation_runs (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS blog_posts (
    id bigserial PRIMARY KEY,
    platform text NOT NULL CHECK (platform IN ('toss', 'coupang', 'threads')),
    product_id text NOT NULL,
    product_name text NOT NULL,
    normal_price integer,
    sale_price integer,
    conditional_price integer,
    price_condition text NOT NULL DEFAULT '',
    affiliate_url text NOT NULL DEFAULT '',
    naver_category text NOT NULL DEFAULT '',
    naver_post_url text NOT NULL DEFAULT '',
    status text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, product_id)
);

CREATE INDEX IF NOT EXISTS blog_posts_status_idx
    ON blog_posts (status, updated_at DESC);

-- Existing installations were initially limited to Toss and Coupang. Replace
-- the generated checks so Threads telemetry works without recreating tables.
ALTER TABLE automation_runs DROP CONSTRAINT IF EXISTS automation_runs_platform_check;
ALTER TABLE automation_runs
    ADD CONSTRAINT automation_runs_platform_check
    CHECK (platform IN ('toss', 'coupang', 'threads'));
ALTER TABLE blog_posts DROP CONSTRAINT IF EXISTS blog_posts_platform_check;
ALTER TABLE blog_posts
    ADD CONSTRAINT blog_posts_platform_check
    CHECK (platform IN ('toss', 'coupang', 'threads'));

CREATE TABLE IF NOT EXISTS toss_collection_runs (
    id uuid PRIMARY KEY,
    source text NOT NULL CHECK (source IN ('best-selling', 'today-deals')),
    requested_size integer NOT NULL CHECK (requested_size BETWEEN 1 AND 100),
    received_count integer NOT NULL DEFAULT 0 CHECK (received_count >= 0),
    status text NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    error_code text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    collected_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS toss_products (
    taca_item_id text PRIMARY KEY,
    product_name text NOT NULL,
    thumbnail_url text NOT NULL DEFAULT '',
    product_url text NOT NULL DEFAULT '',
    display_price integer,
    original_price integer,
    discount_rate integer,
    is_sold_out boolean NOT NULL DEFAULT false,
    review_score numeric,
    review_count integer,
    best_rank integer,
    today_deal_rank integer,
    today_deal_end_at timestamptz,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    last_best_seen_at timestamptz,
    last_today_deal_seen_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS toss_collection_items (
    collection_id uuid NOT NULL REFERENCES toss_collection_runs(id) ON DELETE CASCADE,
    taca_item_id text NOT NULL REFERENCES toss_products(taca_item_id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('best-selling', 'today-deals')),
    product_rank integer,
    observed_price integer,
    observed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, taca_item_id)
);

CREATE TABLE IF NOT EXISTS toss_share_links (
    taca_item_id text PRIMARY KEY REFERENCES toss_products(taca_item_id) ON DELETE CASCADE,
    short_url text NOT NULL,
    origin_url text NOT NULL DEFAULT '',
    publisher_id text NOT NULL DEFAULT '',
    issued_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS toss_collection_runs_collected_idx
    ON toss_collection_runs (collected_at DESC);
CREATE INDEX IF NOT EXISTS toss_products_best_rank_idx
    ON toss_products (best_rank ASC NULLS LAST, last_best_seen_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS toss_products_today_deal_idx
    ON toss_products (today_deal_end_at ASC NULLS LAST, last_today_deal_seen_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS admin_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    password_hash text NOT NULL DEFAULT '',
    password_updated_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


def configured() -> bool:
    return bool(DATABASE_URL and AUTOMATION_API_TOKEN)


def authorized(header_value: str | None) -> bool:
    if not AUTOMATION_API_TOKEN or not header_value:
        return False
    scheme, _, value = header_value.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        value.strip(), AUTOMATION_API_TOKEN
    )


def _connect() -> psycopg.Connection[Any]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    last_error: Exception | None = None
    for attempt in range(DB_MAX_RETRIES):
        try:
            return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)
        except psycopg.OperationalError as exc:
            last_error = exc
            if attempt + 1 < DB_MAX_RETRIES:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError("database connection failed") from last_error


def init_schema() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA_SQL)


def admin_password_hash() -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM admin_settings WHERE singleton = true"
        ).fetchone()
    return str((row or {}).get("password_hash") or "")


def set_admin_password_hash(password_hash: str) -> None:
    value = str(password_hash or "").strip()
    if not value:
        raise ValueError("administrator password hash is required")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_settings (singleton, password_hash, password_updated_at)
            VALUES (true, %s, now())
            ON CONFLICT (singleton) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                password_updated_at = now(),
                updated_at = now()
            """,
            (value,),
        )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if any(word in str(key).lower() for word in ("token", "secret", "password", "authorization", "cookie")) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def write_audit_csv(kind: str, payload: dict[str, Any]) -> None:
    """Append an operational record without ever serializing secret-bearing fields."""
    if not AUTOMATION_AUDIT_CSV_PATH:
        return
    row = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "run_id": str(payload.get("run_id") or payload.get("id") or ""),
        "platform": str(payload.get("platform") or ""),
        "status": str(payload.get("status") or ""),
        "step": str(payload.get("step") or ""),
        "product_id": str(payload.get("product_id") or ""),
        "product_name": str(payload.get("product_name") or ""),
        "retry_count": str(payload.get("retry_count") or 0),
        "naver_post_url": str(payload.get("naver_post_url") or ""),
        "error_code": str(payload.get("error_code") or ""),
        "error_message": str(payload.get("error_message") or ""),
        "context": json.dumps(_redact(payload.get("context") or {}), ensure_ascii=False),
    }
    try:
        path = Path(AUTOMATION_AUDIT_CSV_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(row))
            if not exists:
                writer.writeheader()
            writer.writerow(row)
    except OSError:
        # Database history remains authoritative if local disk logging is unavailable.
        return


def health() -> dict[str, Any]:
    if not configured():
        return {"configured": False, "database": "disabled"}
    try:
        with _connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"configured": True, "database": "ok"}
    except RuntimeError:
        return {"configured": True, "database": "error"}


def _required_text(payload: dict[str, Any], key: str, max_length: int = 500) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required")
    if len(value) > max_length:
        raise ValueError(f"{key} is too long")
    return value


def _platform(payload: dict[str, Any]) -> str:
    value = _required_text(payload, "platform", 20).lower()
    if value not in {"toss", "coupang", "threads"}:
        raise ValueError("platform must be toss, coupang, or threads")
    return value


def _status(payload: dict[str, Any], allowed: set[str]) -> str:
    value = _required_text(payload, "status", 40).upper()
    if value not in allowed:
        raise ValueError("unsupported status")
    return value


def _optional_price(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    number = int(str(value).replace(",", ""))
    if number < 0 or number > 2_000_000_000:
        raise ValueError(f"{key} is out of range")
    return number


def upsert_run(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or uuid.uuid4())
    try:
        parsed_id = uuid.UUID(run_id)
    except ValueError as exc:
        raise ValueError("run_id must be a UUID") from exc
    platform = _platform(payload)
    status = _status(payload, RUN_STATUSES)
    job_name = _required_text(payload, "job_name", 200)
    finished_at = datetime.now(timezone.utc) if status in {"PUBLISHED", "SKIPPED", *ALERT_STATUSES} else None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    values = {
        "id": parsed_id,
        "job_name": job_name,
        "platform": platform,
        "status": status,
        "step": str(payload.get("step", ""))[:200],
        "product_id": str(payload.get("product_id", ""))[:200],
        "product_name": str(payload.get("product_name", ""))[:500],
        "error_code": str(payload.get("error_code", ""))[:100],
        "error_message": str(payload.get("error_message", ""))[:2000],
        "retry_count": max(0, int(payload.get("retry_count", 0))),
        "context": json.dumps(context, ensure_ascii=False),
        "finished_at": finished_at,
    }
    sql = """
        INSERT INTO automation_runs
            (id, job_name, platform, status, step, product_id, product_name,
             error_code, error_message, retry_count, context, finished_at)
        VALUES
            (%(id)s, %(job_name)s, %(platform)s, %(status)s, %(step)s,
             %(product_id)s, %(product_name)s, %(error_code)s,
             %(error_message)s, %(retry_count)s, %(context)s::jsonb, %(finished_at)s)
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            step = EXCLUDED.step,
            product_id = EXCLUDED.product_id,
            product_name = EXCLUDED.product_name,
            error_code = EXCLUDED.error_code,
            error_message = EXCLUDED.error_message,
            retry_count = EXCLUDED.retry_count,
            context = automation_runs.context || EXCLUDED.context,
            finished_at = COALESCE(EXCLUDED.finished_at, automation_runs.finished_at),
            updated_at = now()
        RETURNING id, job_name, platform, status, step, product_id, product_name,
                  error_code, error_message, retry_count, started_at, finished_at, updated_at
    """
    with _connect() as conn:
        row = conn.execute(sql, values).fetchone()
    write_audit_csv("run", {**values, "run_id": str(parsed_id)})
    if status in ALERT_STATUSES:
        action = str(context.get("required_action") or "로그인·가격·이미지·편집기 상태를 확인한 뒤 다시 실행하세요.")
        notify_telegram(
            f"🚨 블로그 자동화 오류\n[{platform.upper()}] {status}\n"
            f"단계: {values['step'] or '-'}\n상품: {values['product_name'] or '-'}\n"
            f"오류: {values['error_message'] or values['error_code'] or '-'}\n"
            f"재시도: {values['retry_count']}회\n"
            f"필요한 조치: {action}"
        )
    return dict(row or {})


def upsert_post(payload: dict[str, Any]) -> dict[str, Any]:
    platform = _platform(payload)
    product_id = _required_text(payload, "product_id", 200)
    product_name = _required_text(payload, "product_name", 500)
    status = _status(payload, POST_STATUSES)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    published_at = datetime.now(timezone.utc) if status == "PUBLISHED" else None
    values = {
        "platform": platform,
        "product_id": product_id,
        "product_name": product_name,
        "normal_price": _optional_price(payload, "normal_price"),
        "sale_price": _optional_price(payload, "sale_price"),
        "conditional_price": _optional_price(payload, "conditional_price"),
        "price_condition": str(payload.get("price_condition", ""))[:300],
        "affiliate_url": str(payload.get("affiliate_url", ""))[:2000],
        "naver_category": str(payload.get("naver_category", ""))[:200],
        "naver_post_url": str(payload.get("naver_post_url", ""))[:2000],
        "status": status,
        "metadata": json.dumps(metadata, ensure_ascii=False),
        "published_at": published_at,
    }
    sql = """
        INSERT INTO blog_posts
            (platform, product_id, product_name, normal_price, sale_price,
             conditional_price, price_condition, affiliate_url, naver_category,
             naver_post_url, status, metadata, published_at)
        VALUES
            (%(platform)s, %(product_id)s, %(product_name)s, %(normal_price)s,
             %(sale_price)s, %(conditional_price)s, %(price_condition)s,
             %(affiliate_url)s, %(naver_category)s, %(naver_post_url)s,
             %(status)s, %(metadata)s::jsonb, %(published_at)s)
        ON CONFLICT (platform, product_id) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            normal_price = COALESCE(EXCLUDED.normal_price, blog_posts.normal_price),
            sale_price = COALESCE(EXCLUDED.sale_price, blog_posts.sale_price),
            conditional_price = COALESCE(EXCLUDED.conditional_price, blog_posts.conditional_price),
            price_condition = CASE WHEN EXCLUDED.price_condition <> '' THEN EXCLUDED.price_condition ELSE blog_posts.price_condition END,
            affiliate_url = CASE WHEN EXCLUDED.affiliate_url <> '' THEN EXCLUDED.affiliate_url ELSE blog_posts.affiliate_url END,
            naver_category = CASE WHEN EXCLUDED.naver_category <> '' THEN EXCLUDED.naver_category ELSE blog_posts.naver_category END,
            naver_post_url = CASE WHEN EXCLUDED.naver_post_url <> '' THEN EXCLUDED.naver_post_url ELSE blog_posts.naver_post_url END,
            status = EXCLUDED.status,
            metadata = blog_posts.metadata || EXCLUDED.metadata,
            published_at = COALESCE(EXCLUDED.published_at, blog_posts.published_at),
            updated_at = now()
        RETURNING *
    """
    with _connect() as conn:
        row = conn.execute(sql, values).fetchone()
    write_audit_csv("post", values)
    if status == "PUBLISHED":
        notify_telegram(
            f"✅ 블로그 발행 완료\n[{platform.upper()}] {product_name}\n"
            f"{values['naver_post_url'] or '(URL 미기록)'}"
        )
    return dict(row or {})


def check_duplicate(platform: str, product_id: str) -> dict[str, Any]:
    if platform not in {"toss", "coupang", "threads"} or not product_id:
        raise ValueError("platform and product_id are required")
    with _connect() as conn:
        row = conn.execute(
            "SELECT platform, product_id, product_name, status, naver_post_url, updated_at "
            "FROM blog_posts WHERE platform = %s AND product_id = %s",
            (platform, product_id),
        ).fetchone()
    return {"exists": bool(row), "post": dict(row) if row else None}


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 100)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, job_name, platform, status, step, product_id, product_name, "
            "error_code, error_message, retry_count, started_at, finished_at, updated_at "
            "FROM automation_runs ORDER BY updated_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def notify_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    data = urllib.parse.urlencode(
        {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096], "disable_web_page_preview": "true"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


TOSS_COLLECTION_SOURCES = {"best-selling", "today-deals"}


def _toss_collection_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized not in TOSS_COLLECTION_SOURCES:
        raise ValueError("unsupported Toss collection source")
    return normalized


def _toss_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Toss numeric field") from exc


def store_toss_collection(
    source: str, requested_size: int, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Persist one documented Toss listing response and retain every observation."""
    normalized_source = _toss_collection_source(source)
    bounded_size = min(max(int(requested_size), 1), 100)
    run_id = uuid.uuid4()
    saved_count = 0
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO toss_collection_runs (id, source, requested_size, received_count, status)
            VALUES (%s, %s, %s, %s, 'COMPLETED')
            """,
            (run_id, normalized_source, bounded_size, len(items)),
        )
        for item in items:
            product_id = str(item.get("taca_item_id") or "").strip()
            product_name = str(item.get("title") or "").strip()
            if not product_id or not product_name:
                continue
            values = {
                "taca_item_id": product_id,
                "product_name": product_name[:500],
                "thumbnail_url": str(item.get("thumbnail_url") or "")[:2000],
                "product_url": str(item.get("product_url") or "")[:2000],
                "display_price": _toss_optional_int(item.get("display_price")),
                "original_price": _toss_optional_int(item.get("original_price")),
                "discount_rate": _toss_optional_int(item.get("discount_rate")),
                "is_sold_out": bool(item.get("is_sold_out")),
                "review_score": item.get("review_score"),
                "review_count": _toss_optional_int(item.get("review_count")),
                "rank": _toss_optional_int(item.get("rank")),
                "end_at": str(item.get("end_at") or "") or None,
                "source": normalized_source,
            }
            conn.execute(
                """
                INSERT INTO toss_products (
                    taca_item_id, product_name, thumbnail_url, product_url,
                    display_price, original_price, discount_rate, is_sold_out,
                    review_score, review_count, best_rank, today_deal_rank,
                    today_deal_end_at, last_best_seen_at, last_today_deal_seen_at
                )
                VALUES (
                    %(taca_item_id)s, %(product_name)s, %(thumbnail_url)s, %(product_url)s,
                    %(display_price)s, %(original_price)s, %(discount_rate)s, %(is_sold_out)s,
                    %(review_score)s, %(review_count)s,
                    CASE WHEN %(source)s = 'best-selling' THEN %(rank)s END,
                    CASE WHEN %(source)s = 'today-deals' THEN %(rank)s END,
                    CASE WHEN %(source)s = 'today-deals' THEN %(end_at)s::timestamptz END,
                    CASE WHEN %(source)s = 'best-selling' THEN now() END,
                    CASE WHEN %(source)s = 'today-deals' THEN now() END
                )
                ON CONFLICT (taca_item_id) DO UPDATE SET
                    product_name = EXCLUDED.product_name,
                    thumbnail_url = CASE WHEN EXCLUDED.thumbnail_url <> '' THEN EXCLUDED.thumbnail_url ELSE toss_products.thumbnail_url END,
                    product_url = CASE WHEN EXCLUDED.product_url <> '' THEN EXCLUDED.product_url ELSE toss_products.product_url END,
                    display_price = EXCLUDED.display_price,
                    original_price = EXCLUDED.original_price,
                    discount_rate = EXCLUDED.discount_rate,
                    is_sold_out = EXCLUDED.is_sold_out,
                    review_score = EXCLUDED.review_score,
                    review_count = EXCLUDED.review_count,
                    best_rank = CASE WHEN %(source)s = 'best-selling' THEN %(rank)s ELSE toss_products.best_rank END,
                    today_deal_rank = CASE WHEN %(source)s = 'today-deals' THEN %(rank)s ELSE toss_products.today_deal_rank END,
                    today_deal_end_at = CASE WHEN %(source)s = 'today-deals' THEN %(end_at)s::timestamptz ELSE toss_products.today_deal_end_at END,
                    last_seen_at = now(),
                    last_best_seen_at = CASE WHEN %(source)s = 'best-selling' THEN now() ELSE toss_products.last_best_seen_at END,
                    last_today_deal_seen_at = CASE WHEN %(source)s = 'today-deals' THEN now() ELSE toss_products.last_today_deal_seen_at END,
                    updated_at = now()
                """,
                values,
            )
            conn.execute(
                """
                INSERT INTO toss_collection_items (collection_id, taca_item_id, source, product_rank, observed_price)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (collection_id, taca_item_id) DO NOTHING
                """,
                (run_id, product_id, normalized_source, values["rank"], values["display_price"]),
            )
            saved_count += 1
    write_audit_csv(
        "toss_collection",
        {
            "run_id": str(run_id),
            "platform": "toss",
            "status": "COMPLETED",
            "step": normalized_source,
            "context": {"requested_size": bounded_size, "saved_count": saved_count},
        },
    )
    return {"id": str(run_id), "source": normalized_source, "saved_count": saved_count}


def record_toss_collection_failure(source: str, requested_size: int, error: Exception) -> dict[str, Any]:
    normalized_source = _toss_collection_source(source)
    run_id = uuid.uuid4()
    bounded_size = min(max(int(requested_size), 1), 100)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO toss_collection_runs
                (id, source, requested_size, received_count, status, error_code, error_message)
            VALUES (%s, %s, %s, 0, 'FAILED', %s, %s)
            """,
            (run_id, normalized_source, bounded_size, type(error).__name__[:100], str(error)[:2000]),
        )
    return {"id": str(run_id), "source": normalized_source, "saved_count": 0, "status": "FAILED"}


def recent_toss_products(source: str = "best-selling", limit: int = 100) -> list[dict[str, Any]]:
    normalized_source = _toss_collection_source(source)
    bounded_limit = min(max(int(limit), 1), 100)
    rank_column = "best_rank" if normalized_source == "best-selling" else "today_deal_rank"
    seen_column = "last_best_seen_at" if normalized_source == "best-selling" else "last_today_deal_seen_at"
    sql = f"""
        SELECT p.taca_item_id, p.product_name, p.thumbnail_url, p.product_url,
               p.display_price, p.original_price, p.discount_rate, p.is_sold_out,
               p.review_score, p.review_count, p.{rank_column} AS rank,
               p.today_deal_end_at, p.first_seen_at, p.last_seen_at,
               l.short_url, l.origin_url, l.issued_at
        FROM toss_products p
        LEFT JOIN toss_share_links l ON l.taca_item_id = p.taca_item_id
        WHERE p.{seen_column} IS NOT NULL
        ORDER BY p.{rank_column} ASC NULLS LAST, p.{seen_column} DESC
        LIMIT %s
    """
    with _connect() as conn:
        rows = conn.execute(sql, (bounded_limit,)).fetchall()
    return [dict(row) for row in rows]
