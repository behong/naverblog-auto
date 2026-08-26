from __future__ import annotations

import csv
import hashlib
import hmac
import json
import secrets
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTOMATION_API_TOKEN = os.getenv("AUTOMATION_API_TOKEN", "").strip()
# This is a deployment setting, not an administrator credential.  When present,
# it is the authoritative source for Open API share-link issuance.
TOSS_OPEN_API_PUBLISHER_ID = os.getenv("TOSS_OPEN_API_PUBLISHER_ID", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_APPROVAL_CHAT_ID = os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
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
    toss_publisher_id text NOT NULL DEFAULT '',
    password_updated_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE admin_settings ADD COLUMN IF NOT EXISTS toss_publisher_id text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS publication_approval_batches (
    id uuid PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'HELD', 'EXPIRED')),
    source text NOT NULL DEFAULT 'toss-daily',
    item_count integer NOT NULL CHECK (item_count > 0),
    summary jsonb NOT NULL DEFAULT '[]'::jsonb,
    expected_chat_id text NOT NULL DEFAULT '',
    telegram_message_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    decided_at timestamptz,
    decided_by_user_id text NOT NULL DEFAULT ''
);
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS extension_claimed_at timestamptz;
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS publish_state text NOT NULL DEFAULT 'NOT_STARTED';
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS publish_token_hash text NOT NULL DEFAULT '';
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS publish_started_at timestamptz;
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS publish_finished_at timestamptz;
ALTER TABLE publication_approval_batches
    ADD COLUMN IF NOT EXISTS publish_error text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS publication_approval_batches_pending_idx
    ON publication_approval_batches (status, expires_at ASC);

CREATE TABLE IF NOT EXISTS extension_devices (
    id uuid PRIMARY KEY,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    enabled boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS publication_approval_events (
    id bigserial PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES publication_approval_batches(id) ON DELETE CASCADE,
    action text NOT NULL CHECK (action IN ('APPROVED', 'HELD', 'EXPIRED', 'REJECTED')),
    actor_user_id text NOT NULL DEFAULT '',
    actor_chat_id text NOT NULL DEFAULT '',
    recorded_at timestamptz NOT NULL DEFAULT now(),
    detail text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS publication_approval_events_batch_idx
    ON publication_approval_events (batch_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS scheduled_toss_publish_items (
    id uuid PRIMARY KEY,
    master_batch_id uuid NOT NULL REFERENCES publication_approval_batches(id) ON DELETE CASCADE,
    release_batch_id uuid UNIQUE REFERENCES publication_approval_batches(id) ON DELETE SET NULL,
    schedule_date date NOT NULL,
    sequence_no integer NOT NULL CHECK (sequence_no BETWEEN 1 AND 10),
    product_id text NOT NULL,
    product_name text NOT NULL DEFAULT '',
    expected_price integer,
    status text NOT NULL CHECK (status IN ('QUEUED', 'RELEASED', 'PUBLISHED', 'FAILED_PRE_SUBMIT', 'PUBLISH_UNKNOWN', 'SKIPPED')) DEFAULT 'QUEUED',
    created_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    finished_at timestamptz,
    error_message text NOT NULL DEFAULT '',
    UNIQUE (master_batch_id, sequence_no),
    UNIQUE (schedule_date, product_id)
);
CREATE INDEX IF NOT EXISTS scheduled_toss_publish_due_idx
    ON scheduled_toss_publish_items (schedule_date, status, sequence_no);

CREATE TABLE IF NOT EXISTS scheduled_toss_publish_history (
    original_item_id uuid PRIMARY KEY,
    master_batch_id uuid NOT NULL,
    release_batch_id uuid,
    schedule_date date NOT NULL,
    sequence_no integer NOT NULL,
    product_id text NOT NULL,
    product_name text NOT NULL DEFAULT '',
    expected_price integer,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    released_at timestamptz,
    finished_at timestamptz,
    error_message text NOT NULL DEFAULT '',
    archived_at timestamptz NOT NULL DEFAULT now(),
    archive_reason text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS scheduled_toss_publish_history_date_idx
    ON scheduled_toss_publish_history (schedule_date, status, archived_at DESC);

CREATE TABLE IF NOT EXISTS telegram_bot_state (
    state_key text PRIMARY KEY,
    state_value text NOT NULL DEFAULT '',
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


def _admin_toss_publisher_id_from_database() -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT toss_publisher_id FROM admin_settings WHERE singleton = true"
        ).fetchone()
    return str((row or {}).get("toss_publisher_id") or "")


def admin_toss_publisher_settings() -> dict[str, str | bool]:
    """Return the effective publisher setting without exposing its UUID.

    A deployment environment value always wins.  The existing administrator
    setting remains a migration-friendly fallback for installations that have
    not yet moved the value to their environment configuration.
    """
    if TOSS_OPEN_API_PUBLISHER_ID:
        return {"configured": True, "source": "environment"}
    database_value = _admin_toss_publisher_id_from_database()
    if database_value:
        return {"configured": True, "source": "database"}
    return {"configured": False, "source": "unset"}


def admin_toss_publisher_id() -> str:
    if TOSS_OPEN_API_PUBLISHER_ID:
        return TOSS_OPEN_API_PUBLISHER_ID
    return _admin_toss_publisher_id_from_database()


def set_admin_toss_publisher_id(publisher_id: str) -> None:
    value = str(publisher_id or "").strip()
    if not value:
        raise ValueError("Toss publisher ID is required")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_settings (singleton, toss_publisher_id)
            VALUES (true, %s)
            ON CONFLICT (singleton) DO UPDATE SET
                toss_publisher_id = EXCLUDED.toss_publisher_id,
                updated_at = now()
            """,
            (value,),
        )


APPROVAL_ACTIONS = {"APPROVED", "HELD"}
KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")
MOBILE_RELEASE_PAUSED_STATE_KEY = "mobile_toss_release_paused"
TOSS_AUTO_PUBLISH_ENABLED_STATE_KEY = "toss_auto_publish_enabled"


def korea_today() -> date:
    return datetime.now(KOREA_TIMEZONE).date()


def mobile_toss_release_paused() -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT state_value FROM telegram_bot_state WHERE state_key = %s",
            (MOBILE_RELEASE_PAUSED_STATE_KEY,),
        ).fetchone()
    return str((row or {}).get("state_value") or "").strip() == "1"


def set_mobile_toss_release_paused(paused: bool) -> bool:
    value = "1" if paused else "0"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot_state (state_key, state_value)
            VALUES (%s, %s)
            ON CONFLICT (state_key) DO UPDATE SET
                state_value = EXCLUDED.state_value,
                updated_at = now()
            """,
            (MOBILE_RELEASE_PAUSED_STATE_KEY, value),
        )
    return paused


def toss_auto_publish_enabled() -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT state_value FROM telegram_bot_state WHERE state_key = %s",
            (TOSS_AUTO_PUBLISH_ENABLED_STATE_KEY,),
        ).fetchone()
    return str((row or {}).get("state_value") or "").strip() == "1"


def set_toss_auto_publish_enabled(enabled: bool) -> bool:
    value = "1" if enabled else "0"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot_state (state_key, state_value)
            VALUES (%s, %s)
            ON CONFLICT (state_key) DO UPDATE SET
                state_value = EXCLUDED.state_value,
                updated_at = now()
            """,
            (TOSS_AUTO_PUBLISH_ENABLED_STATE_KEY, value),
        )
    return enabled


def mobile_toss_status() -> dict[str, Any]:
    today = korea_today()
    with _connect() as conn:
        queue_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s
            GROUP BY status
            """,
            (today,),
        ).fetchall()
        window_rows = conn.execute(
            """
            SELECT source, status, item_count
            FROM publication_approval_batches
            WHERE source IN ('toss-draft-window:morning', 'toss-draft-window:midday', 'toss-draft-window:evening')
              AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY created_at
            """,
            (today,),
        ).fetchall()
    counts = {"QUEUED": 0, "RELEASED": 0, "PUBLISHED": 0, "FAILED_PRE_SUBMIT": 0, "PUBLISH_UNKNOWN": 0, "SKIPPED": 0}
    for row in queue_rows:
        counts[str(row["status"])] = int(row["count"])
    return {
        "date": today.isoformat(),
        "release_paused": mobile_toss_release_paused(),
        "auto_publish_enabled": toss_auto_publish_enabled(),
        "queue": counts,
        "windows": [
            {"source": str(row["source"]), "status": str(row["status"]), "item_count": int(row["item_count"])}
            for row in window_rows
        ],
    }


def active_telegram_approval_chat_id() -> str:
    if TELEGRAM_APPROVAL_CHAT_ID:
        return TELEGRAM_APPROVAL_CHAT_ID
    if not DATABASE_URL:
        return TELEGRAM_CHAT_ID
    with _connect() as conn:
        row = conn.execute(
            "SELECT state_value FROM telegram_bot_state WHERE state_key = 'approval_chat_id'"
        ).fetchone()
    selected = str((row or {}).get("state_value") or "").strip()
    return selected or TELEGRAM_CHAT_ID


def create_extension_device() -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO extension_devices (id, token_hash) VALUES (%s, %s)",
            (uuid.uuid4(), token_hash),
        )
    return raw_token


def extension_device_valid(raw_token: str) -> bool:
    token = str(raw_token or "").strip()
    if len(token) < 24:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE extension_devices
            SET last_seen_at = now()
            WHERE token_hash = %s AND enabled = true
            RETURNING id
            """,
            (token_hash,),
        ).fetchone()
    return bool(row)


def latest_unclaimed_approved_publication() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, summary, source, created_at, decided_at
            FROM publication_approval_batches
            WHERE status = 'APPROVED'
              AND item_count = 1
              AND extension_claimed_at IS NULL
              AND publish_state = 'NOT_STARTED'
              AND source NOT LIKE 'toss-draft-window:%'
            ORDER BY decided_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def mark_publication_approval_claimed(batch_id: str) -> bool:
    parsed_id = uuid.UUID(str(batch_id))
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE publication_approval_batches
            SET extension_claimed_at = now()
            WHERE id = %s AND status = 'APPROVED' AND extension_claimed_at IS NULL
            RETURNING id
            """,
            (parsed_id,),
        ).fetchone()
    return bool(row)


MIN_CROSS_PLATFORM_PUBLISH_GAP_MINUTES = 60


def enforce_cross_platform_publish_gap(conn, platform: str) -> None:
    """Prevent Toss and Coupang from starting Naver publication too close together."""
    normalized = str(platform or '').strip().lower()
    if normalized not in {'toss', 'coupang'}:
        return
    row = conn.execute(
        """
        SELECT publish_started_at, source
        FROM publication_approval_batches
        WHERE publish_started_at IS NOT NULL
          AND source IN ('coupang-publish', 'toss-daily', 'toss-scheduled-release',
                         'toss-draft-window:morning', 'toss-draft-window:midday',
                         'toss-draft-window:evening')
        ORDER BY publish_started_at DESC
        LIMIT 1
        FOR UPDATE
        """
    ).fetchone()
    if not row or not row.get('publish_started_at'):
        return
    previous_source = str(row.get('source') or '')
    previous_platform = 'coupang' if previous_source == 'coupang-publish' else 'toss'
    if previous_platform == normalized:
        return
    previous = row['publish_started_at']
    current = datetime.now(timezone.utc)
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    elapsed_minutes = (current - previous).total_seconds() / 60
    if elapsed_minutes < MIN_CROSS_PLATFORM_PUBLISH_GAP_MINUTES:
        remaining = max(1, int(MIN_CROSS_PLATFORM_PUBLISH_GAP_MINUTES - elapsed_minutes + 0.999))
        raise ValueError(f'토스·쿠팡 발행 간격을 위해 {remaining}분 후 다시 실행합니다.')


def release_latest_extension_claim_for_retry() -> bool:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE publication_approval_batches
            SET extension_claimed_at = NULL
            WHERE id = (
                SELECT id FROM publication_approval_batches
                WHERE status = 'APPROVED' AND item_count = 1 AND extension_claimed_at IS NOT NULL
                ORDER BY decided_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            )
            RETURNING id
            """
        ).fetchone()
    return bool(row)


def create_scheduled_toss_publish_items(
    master_batch_id: str,
    schedule_date: date,
    items: list[dict[str, Any]],
) -> int:
    """Persist up to ten already-validated items behind one Telegram approval."""
    parsed_master_id = uuid.UUID(str(master_batch_id))
    if not items or len(items) > 10:
        raise ValueError("scheduled Toss queue requires 1 to 10 items")
    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) AS max_sequence
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s
            """,
            (schedule_date,),
        ).fetchone()
        sequence_offset = int((existing or {}).get("max_sequence") or 0)
        for index, item in enumerate(items, start=1):
            product_id = str(item.get("product_id") or "").strip()
            product_name = " ".join(str(item.get("product_name") or "").split())
            try:
                expected_price = int(item.get("price"))
            except (TypeError, ValueError) as exc:
                raise ValueError("scheduled Toss item price is invalid") from exc
            if not product_id or not product_name or expected_price <= 0:
                raise ValueError("scheduled Toss item is incomplete")
            conn.execute(
                """
                INSERT INTO scheduled_toss_publish_items
                    (id, master_batch_id, schedule_date, sequence_no, product_id, product_name, expected_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (uuid.uuid4(), parsed_master_id, schedule_date, sequence_offset + index, product_id[:200], product_name[:500], expected_price),
            )
    return len(items)


def release_next_scheduled_toss_item(schedule_date: date) -> dict[str, Any]:
    """Create exactly one single-item APPROVED batch from an approved daily master queue."""
    if mobile_toss_release_paused():
        return {"released": False, "reason": "mobile_release_paused"}
    with _connect() as conn:
        active = conn.execute(
            """
            SELECT q.id
            FROM scheduled_toss_publish_items q
            WHERE q.schedule_date = %s AND q.status = 'RELEASED'
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (schedule_date,),
        ).fetchone()
        if active:
            return {"released": False, "reason": "previous_item_in_progress"}
        item_row = conn.execute(
            """
            SELECT q.*, b.expected_chat_id
            FROM scheduled_toss_publish_items q
            JOIN publication_approval_batches b ON b.id = q.master_batch_id
            WHERE q.schedule_date = %s
              AND q.status = 'QUEUED'
              AND b.status = 'APPROVED'
            ORDER BY q.sequence_no ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (schedule_date,),
        ).fetchone()
        if not item_row:
            return {"released": False, "reason": "no_approved_queued_item"}
        item = dict(item_row)
        summary = [{
            "product_id": str(item["product_id"]),
            "product_name": str(item["product_name"]),
            "price": int(item["expected_price"]),
        }]
        release_batch_id = uuid.uuid4()
        batch = conn.execute(
            """
            INSERT INTO publication_approval_batches
                (id, status, source, item_count, summary, expected_chat_id, expires_at, decided_at)
            VALUES (%s, 'APPROVED', 'toss-scheduled-release', 1, %s::jsonb, %s, now() + interval '1 day', now())
            RETURNING id
            """,
            (release_batch_id, json.dumps(summary, ensure_ascii=False), str(item.get("expected_chat_id") or "")),
        ).fetchone()
        conn.execute(
            """
            UPDATE scheduled_toss_publish_items
            SET status = 'RELEASED', release_batch_id = %s, released_at = now(), error_message = ''
            WHERE id = %s
            """,
            (batch["id"], item["id"]),
        )
    return {"released": True, "batch_id": str(release_batch_id), "product_id": str(item["product_id"]), "sequence_no": int(item["sequence_no"])}


def archive_terminal_scheduled_toss_items(schedule_date: date, archive_reason: str) -> int:
    """Preserve terminal queue rows in history before freeing today's active queue slots."""
    clean_reason = " ".join(str(archive_reason or "").split())[:200]
    terminal_states = ("PUBLISHED", "FAILED_PRE_SUBMIT", "PUBLISH_UNKNOWN", "SKIPPED")
    with _connect() as conn:
        rows = conn.execute(
            """
            DELETE FROM scheduled_toss_publish_items
            WHERE schedule_date = %s AND status = ANY(%s)
            RETURNING id, master_batch_id, release_batch_id, schedule_date, sequence_no,
                      product_id, product_name, expected_price, status, created_at,
                      released_at, finished_at, error_message
            """,
            (schedule_date, list(terminal_states)),
        ).fetchall()
        for row in rows:
            item = dict(row)
            conn.execute(
                """
                INSERT INTO scheduled_toss_publish_history
                    (original_item_id, master_batch_id, release_batch_id, schedule_date, sequence_no,
                     product_id, product_name, expected_price, status, created_at, released_at,
                     finished_at, error_message, archive_reason)
                VALUES (%(id)s, %(master_batch_id)s, %(release_batch_id)s, %(schedule_date)s, %(sequence_no)s,
                        %(product_id)s, %(product_name)s, %(expected_price)s, %(status)s, %(created_at)s,
                        %(released_at)s, %(finished_at)s, %(error_message)s, %(archive_reason)s)
                ON CONFLICT (original_item_id) DO NOTHING
                """,
                {**item, "archive_reason": clean_reason},
            )
    return len(rows)


def scheduled_toss_queue_status(schedule_date: date) -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM scheduled_toss_publish_items
            WHERE schedule_date = %s
            GROUP BY status
            """,
            (schedule_date,),
        ).fetchall()
    result = {"QUEUED": 0, "RELEASED": 0, "PUBLISHED": 0, "FAILED_PRE_SUBMIT": 0, "PUBLISH_UNKNOWN": 0, "SKIPPED": 0}
    for row in rows:
        result[str(row["status"])] = int(row["count"])
    return result


def claim_latest_approved_publication() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, summary, source, created_at, decided_at
            FROM publication_approval_batches
            WHERE status = 'APPROVED'
              AND item_count = 1
              AND extension_claimed_at IS NULL
              AND publish_state = 'NOT_STARTED'
              AND source NOT LIKE 'toss-draft-window:%'
            ORDER BY decided_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE publication_approval_batches SET extension_claimed_at = now() WHERE id = %s",
            (row["id"],),
        )
    return dict(row)


PUBLISH_TERMINAL_STATES = {"PUBLISHED", "PUBLISH_UNKNOWN", "FAILED_PRE_SUBMIT"}


def _publish_product_values(product: dict[str, Any]) -> dict[str, Any]:
    platform = str(product.get("platform") or "toss").strip().lower()
    if platform != "toss":
        raise ValueError("only Toss automatic publishing is supported")
    product_id = str(product.get("product_id") or "").strip()
    product_name = " ".join(str(product.get("product_name") or "").split())
    affiliate_url = str(product.get("affiliate_url") or "").strip()
    naver_category = str(product.get("naver_category") or "").strip()
    sale_price = _optional_price(product, "sale_price")
    if not product_id or not product_name or not affiliate_url.startswith("https://"):
        raise ValueError("publish product data is incomplete")
    if sale_price is None or sale_price <= 0:
        raise ValueError("publish price is invalid")
    if naver_category != "39":
        raise ValueError("Naver category must be 39")
    return {
        "platform": platform,
        "product_id": product_id[:200],
        "product_name": product_name[:500],
        "sale_price": sale_price,
        "affiliate_url": affiliate_url[:2000],
        "naver_category": naver_category,
    }


def begin_extension_publish(batch_id: str, product: dict[str, Any]) -> dict[str, Any]:
    """Acquire the single-use publication lock immediately before clicking Naver publish.

    The row-level lock and the PUBLISHING blog_post record make a duplicate click or
    a second device fail closed.  Only the SHA-256 hash of the short-lived result
    token is persisted.
    """
    parsed_id = uuid.UUID(str(batch_id))
    values = _publish_product_values(product)
    with _connect() as conn:
        enforce_cross_platform_publish_gap(conn, values['platform'])
        batch_row = conn.execute(
            """
            SELECT id, status, summary, extension_claimed_at, publish_state
            FROM publication_approval_batches
            WHERE id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        if not batch_row:
            raise ValueError("approval batch not found")
        batch = dict(batch_row)
        if batch.get("status") != "APPROVED" or batch.get("extension_claimed_at") is None:
            raise ValueError("approval batch is not ready for publishing")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1 or str((summary[0] or {}).get("product_id") or "") != values["product_id"]:
            raise ValueError("approval batch product does not match the publish request")
        if str(batch.get("publish_state") or "NOT_STARTED") in {"PUBLISHING", "PUBLISHED", "PUBLISH_UNKNOWN"}:
            raise ValueError("this approval batch already has a publish attempt")
        existing = conn.execute(
            """
            SELECT status, naver_post_url
            FROM blog_posts
            WHERE platform = %s AND product_id = %s
            FOR UPDATE
            """,
            (values["platform"], values["product_id"]),
        ).fetchone()
        if existing and str(existing.get("status") or "") in {"PUBLISHING", "PUBLISHED"}:
            raise ValueError("this product is already publishing or has been published")
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        context = json.dumps({"approval_batch_id": str(parsed_id), "publish_mode": "telegram_one_tap"}, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO blog_posts
                (platform, product_id, product_name, sale_price, affiliate_url,
                 naver_category, status, metadata)
            VALUES (%(platform)s, %(product_id)s, %(product_name)s, %(sale_price)s,
                    %(affiliate_url)s, %(naver_category)s, 'PUBLISHING', %(metadata)s::jsonb)
            ON CONFLICT (platform, product_id) DO UPDATE SET
                product_name = EXCLUDED.product_name,
                sale_price = EXCLUDED.sale_price,
                affiliate_url = EXCLUDED.affiliate_url,
                naver_category = EXCLUDED.naver_category,
                status = 'PUBLISHING',
                metadata = blog_posts.metadata || EXCLUDED.metadata,
                updated_at = now()
            """,
            {**values, "metadata": context},
        )
        conn.execute(
            """
            UPDATE publication_approval_batches
            SET publish_state = 'PUBLISHING', publish_token_hash = %s,
                publish_started_at = now(), publish_finished_at = NULL, publish_error = ''
            WHERE id = %s
            """,
            (token_hash, parsed_id),
        )
    return {"publish_token": raw_token, "publish_state": "PUBLISHING"}


def record_extension_pre_publish_failure(batch_id: str, error_message: str) -> dict[str, Any]:
    """Record a verified pre-click failure so a scheduled RELEASED item cannot block the queue."""
    parsed_id = uuid.UUID(str(batch_id))
    error_text = str(error_message or "자동 입력 또는 공개 전 검증에 실패했습니다.").strip()[:2000]
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, status, summary, publish_state, extension_claimed_at
            FROM publication_approval_batches
            WHERE id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("approval batch not found")
        batch = dict(row)
        if batch.get("status") != "APPROVED":
            raise ValueError("approval batch is not ready for pre-publish failure recording")
        if str(batch.get("publish_state") or "NOT_STARTED") != "NOT_STARTED":
            raise ValueError("approval batch has already entered publication")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1:
            raise ValueError("approval batch must contain exactly one product")
        product_name = " ".join(str((summary[0] or {}).get("product_name") or "상품").split())
        scheduled = conn.execute(
            """
            SELECT sequence_no
            FROM scheduled_toss_publish_items
            WHERE release_batch_id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE publication_approval_batches
            SET publish_state = 'FAILED_PRE_SUBMIT', publish_finished_at = now(), publish_error = %s
            WHERE id = %s
            """,
            (error_text, parsed_id),
        )
        conn.execute(
            """
            UPDATE scheduled_toss_publish_items
            SET status = 'FAILED_PRE_SUBMIT', finished_at = now(), error_message = %s
            WHERE release_batch_id = %s AND status = 'RELEASED'
            """,
            (error_text, parsed_id),
        )
    sequence_text = f"\n오늘 진행: {int(scheduled['sequence_no'])}/10건" if scheduled else ""
    notify_telegram_approval(
        "❌ 공개 전 자동 입력이 중단됐습니다.\n"
        f"상품: {product_name}{sequence_text}\n"
        f"사유: {error_text}\n공개하지 않았습니다. 다음 예약 항목은 별도 검증 후 진행합니다."
    )
    return {"batch_id": str(parsed_id), "outcome": "FAILED_PRE_SUBMIT"}


def record_extension_preflight_success(batch_id: str) -> dict[str, Any]:
    """Record a non-publishing editor preflight after title/link/image input succeeds."""
    parsed_id = uuid.UUID(str(batch_id))
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, status, source, summary, publish_state, extension_claimed_at
            FROM publication_approval_batches
            WHERE id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("approval batch not found")
        batch = dict(row)
        if batch.get("status") != "APPROVED" or batch.get("extension_claimed_at") is None:
            raise ValueError("approval batch is not ready for preflight recording")
        if str(batch.get("source") or "") != "toss-preflight":
            raise ValueError("approval batch is not a preflight batch")
        if str(batch.get("publish_state") or "NOT_STARTED") != "NOT_STARTED":
            raise ValueError("approval batch has already entered publication")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1:
            raise ValueError("approval batch must contain exactly one product")
        product_name = " ".join(str((summary[0] or {}).get("product_name") or "상품").split())
        conn.execute(
            """
            UPDATE publication_approval_batches
            SET publish_state = 'PREFLIGHT_PASSED', publish_finished_at = now(), publish_error = ''
            WHERE id = %s
            """,
            (parsed_id,),
        )
    notify_telegram_approval(
        "✅ 네이버 입력 사전 검증을 통과했습니다.\n"
        f"상품: {product_name}\n"
        "제목·일반 링크·원본 이미지를 확인했습니다. 발행 버튼은 누르지 않았습니다."
    )
    return {"batch_id": str(parsed_id), "outcome": "PREFLIGHT_PASSED"}


def record_extension_publish_result(
    batch_id: str,
    publish_token: str,
    outcome: str,
    naver_post_url: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    """Finalize a locked publication without allowing an ambiguous click to retry."""
    parsed_id = uuid.UUID(str(batch_id))
    raw_token = str(publish_token or "").strip()
    supplied_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest() if raw_token else ""
    normalized_outcome = str(outcome or "").strip().upper()
    if normalized_outcome not in PUBLISH_TERMINAL_STATES:
        raise ValueError("unsupported publish result")
    clean_url = str(naver_post_url or "").strip()[:2000]
    error_text = str(error_message or "").strip()[:2000]
    if normalized_outcome == "PUBLISHED" and not clean_url:
        raise ValueError("published result requires a Naver post URL")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, status, summary, publish_state, publish_token_hash
            FROM publication_approval_batches
            WHERE id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        if not row:
            raise ValueError("approval batch not found")
        batch = dict(row)
        if batch.get("publish_state") != "PUBLISHING":
            raise ValueError("approval batch is not awaiting a publish result")
        if not raw_token or not hmac.compare_digest(str(batch.get("publish_token_hash") or ""), supplied_hash):
            raise ValueError("publish result token is invalid")
        summary = batch.get("summary") if isinstance(batch.get("summary"), list) else []
        if len(summary) != 1:
            raise ValueError("approval batch must contain exactly one product")
        product_id = str((summary[0] or {}).get("product_id") or "").strip()
        if not product_id:
            raise ValueError("approval batch product is missing")
        if normalized_outcome == "PUBLISHED":
            conn.execute(
                """
                UPDATE blog_posts
                SET status = 'PUBLISHED', naver_post_url = %s, published_at = now(), updated_at = now(),
                    metadata = metadata || %s::jsonb
                WHERE platform = 'toss' AND product_id = %s
                """,
                (clean_url, json.dumps({"approval_batch_id": str(parsed_id), "publish_mode": "telegram_one_tap"}, ensure_ascii=False), product_id),
            )
        elif normalized_outcome == "FAILED_PRE_SUBMIT":
            conn.execute(
                """
                UPDATE blog_posts
                SET status = 'FAILED', updated_at = now(),
                    metadata = metadata || %s::jsonb
                WHERE platform = 'toss' AND product_id = %s
                """,
                (json.dumps({"approval_batch_id": str(parsed_id), "publish_error": error_text}, ensure_ascii=False), product_id),
            )
        conn.execute(
            """
            UPDATE publication_approval_batches
            SET publish_state = %s, publish_finished_at = now(), publish_error = %s
            WHERE id = %s
            """,
            (normalized_outcome, error_text, parsed_id),
        )
        scheduled = conn.execute(
            """
            SELECT sequence_no
            FROM scheduled_toss_publish_items
            WHERE release_batch_id = %s
            FOR UPDATE
            """,
            (parsed_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE scheduled_toss_publish_items
            SET status = %s, finished_at = now(), error_message = %s
            WHERE release_batch_id = %s AND status = 'RELEASED'
            """,
            (normalized_outcome, error_text, parsed_id),
        )
    product_name = " ".join(str((summary[0] or {}).get("product_name") or "상품").split())
    sequence_text = f"\n오늘 진행: {int(scheduled['sequence_no'])}/10건" if scheduled else ""
    if normalized_outcome == "PUBLISHED":
        notify_telegram_approval(
            f"✅ 블로그 발행 완료\n상품: {product_name}\n공개 글: {clean_url}{sequence_text}"
        )
    elif normalized_outcome == "PUBLISH_UNKNOWN":
        notify_telegram_approval(
            "⚠️ 발행 후 공개 URL을 자동 확인하지 못했습니다.\n"
            f"상품: {product_name}{sequence_text}\n"
            "중복 방지를 위해 자동 재클릭은 차단됐습니다.\n"
            "휴대폰 확인: https://blog.naver.com/sijm\n"
            "최신 글이 보이면 그 URL을 보내고, 보이지 않으면 ‘미발행’이라고 알려 주세요."
        )
    else:
        notify_telegram_approval(
            "❌ 네이버 공개 전 검증 또는 버튼 탐색에 실패했습니다.\n"
            f"사유: {error_text or '알 수 없는 오류'}\n공개하지 않았습니다."
        )
    return {"batch_id": str(parsed_id), "outcome": normalized_outcome, "naver_post_url": clean_url}


def set_telegram_approval_chat_id(chat_id: str) -> None:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("invalid Telegram approval chat ID")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot_state (state_key, state_value)
            VALUES ('approval_chat_id', %s)
            ON CONFLICT (state_key) DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = now()
            """,
            (normalized_chat_id[:100],),
        )


def set_telegram_approval_chat_candidate(chat_id: str) -> None:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot_state (state_key, state_value)
            VALUES ('approval_chat_candidate_id', %s)
            ON CONFLICT (state_key) DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = now()
            """,
            (normalized_chat_id[:100],),
        )


def activate_telegram_approval_chat_candidate() -> bool:
    with _connect() as conn:
        candidate = conn.execute(
            "SELECT state_value FROM telegram_bot_state WHERE state_key = 'approval_chat_candidate_id'"
        ).fetchone()
    value = str((candidate or {}).get("state_value") or "").strip()
    if not value:
        return False
    set_telegram_approval_chat_id(value)
    return True


def create_publication_approval_batch(
    summary: list[dict[str, Any]],
    expires_at: datetime,
    source: str = "toss-daily",
    *,
    auto_approve: bool = False,
) -> dict[str, Any]:
    approval_chat_id = active_telegram_approval_chat_id()
    if not approval_chat_id:
        raise RuntimeError("TELEGRAM approval chat is not configured")
    if not summary:
        raise ValueError("approval batch requires at least one item")
    if len(summary) > 10:
        raise ValueError("approval batch cannot contain more than 10 items")
    if expires_at.tzinfo is None:
        raise ValueError("approval expiry must include a timezone")
    batch_id = uuid.uuid4()
    initial_status = 'APPROVED' if auto_approve else 'PENDING'
    decided_at_sql = ', now()' if auto_approve else ', NULL'
    with _connect() as conn:
        row = conn.execute(
            f"""
            INSERT INTO publication_approval_batches
                (id, status, source, item_count, summary, expected_chat_id, expires_at, decided_at)
            VALUES (%s, '{initial_status}', %s, %s, %s::jsonb, %s, %s{decided_at_sql})
            RETURNING id, status, source, item_count, summary, created_at, expires_at
            """,
            (
                batch_id,
                str(source or "toss-daily")[:100],
                len(summary),
                json.dumps(summary, ensure_ascii=False),
                approval_chat_id,
                expires_at,
            ),
        ).fetchone()
    return dict(row or {})


def create_auto_publication_batch(
    summary: list[dict[str, Any]],
    source: str = "toss-daily",
) -> dict[str, Any]:
    """Create a validated scheduled batch that the user explicitly authorized for unattended publishing."""
    approval_chat_id = active_telegram_approval_chat_id()
    if not approval_chat_id:
        raise RuntimeError("TELEGRAM approval chat is not configured")
    if not summary or len(summary) > 10:
        raise ValueError("auto publication batch requires 1 to 10 items")
    batch_id = uuid.uuid4()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO publication_approval_batches
                (id, status, source, item_count, summary, expected_chat_id, expires_at, decided_at)
            VALUES (%s, 'APPROVED', %s, %s, %s::jsonb, %s, now() + interval '1 day', now())
            RETURNING id, status, source, item_count, summary, created_at, expires_at, decided_at
            """,
            (
                batch_id,
                str(source or "toss-daily")[:100],
                len(summary),
                json.dumps(summary, ensure_ascii=False),
                approval_chat_id,
            ),
        ).fetchone()
    return dict(row or {})


def auto_approve_publication_batch(batch_id: str) -> dict[str, Any]:
    """Approve a fully validated batch without requiring a Telegram button click."""
    parsed_id = uuid.UUID(str(batch_id))
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE publication_approval_batches
            SET status = 'APPROVED', decided_at = now()
            WHERE id = %s AND status = 'PENDING' AND expires_at > now()
            RETURNING id, status, source, item_count, summary, created_at, expires_at, decided_at
            """,
            (parsed_id,),
        ).fetchone()
    if not row:
        raise ValueError("자동 발행 승인 배치를 만들지 못했습니다.")
    return dict(row)


def set_publication_approval_expected_chat_id(batch_id: str, chat_id: str) -> None:
    parsed_id = uuid.UUID(str(batch_id))
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("invalid Telegram chat ID")
    with _connect() as conn:
        conn.execute(
            "UPDATE publication_approval_batches SET expected_chat_id = %s WHERE id = %s",
            (normalized_chat_id[:100], parsed_id),
        )


def set_publication_approval_message_id(batch_id: str, message_id: int) -> None:
    parsed_id = uuid.UUID(str(batch_id))
    parsed_message_id = int(message_id)
    if parsed_message_id <= 0:
        raise ValueError("invalid Telegram message ID")
    with _connect() as conn:
        conn.execute(
            "UPDATE publication_approval_batches SET telegram_message_id = %s WHERE id = %s",
            (parsed_message_id, parsed_id),
        )


def resolve_publication_approval(
    batch_id: str,
    action: str,
    actor_chat_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    parsed_id = uuid.UUID(str(batch_id))
    normalized_action = str(action or "").strip().upper()
    if normalized_action not in APPROVAL_ACTIONS:
        raise ValueError("unsupported approval action")
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM publication_approval_batches WHERE id = %s FOR UPDATE",
            (parsed_id,),
        ).fetchone()
        if not row:
            return {"accepted": False, "reason": "not_found"}
        batch = dict(row)
        if str(batch.get("expected_chat_id") or "") != str(actor_chat_id or ""):
            conn.execute(
                """
                INSERT INTO publication_approval_events
                    (batch_id, action, actor_user_id, actor_chat_id, detail)
                VALUES (%s, 'REJECTED', %s, %s, 'unexpected_chat')
                """,
                (parsed_id, str(actor_user_id or "")[:100], str(actor_chat_id or "")[:100]),
            )
            return {"accepted": False, "reason": "unexpected_chat"}
        if batch.get("status") != "PENDING":
            return {"accepted": False, "reason": str(batch.get("status") or "resolved").lower()}
        now = datetime.now(timezone.utc)
        if batch.get("expires_at") is not None and batch["expires_at"] <= now:
            conn.execute(
                """
                UPDATE publication_approval_batches
                SET status = 'EXPIRED', decided_at = now(), decided_by_user_id = %s
                WHERE id = %s
                """,
                (str(actor_user_id or "")[:100], parsed_id),
            )
            conn.execute(
                """
                INSERT INTO publication_approval_events
                    (batch_id, action, actor_user_id, actor_chat_id, detail)
                VALUES (%s, 'EXPIRED', %s, %s, 'expired_before_response')
                """,
                (parsed_id, str(actor_user_id or "")[:100], str(actor_chat_id or "")[:100]),
            )
            return {"accepted": False, "reason": "expired"}
        updated = conn.execute(
            """
            UPDATE publication_approval_batches
            SET status = %s, decided_at = now(), decided_by_user_id = %s
            WHERE id = %s AND status = 'PENDING'
            RETURNING id, status, item_count, summary, telegram_message_id, expires_at
            """,
            (normalized_action, str(actor_user_id or "")[:100], parsed_id),
        ).fetchone()
        if not updated:
            return {"accepted": False, "reason": "resolved"}
        conn.execute(
            """
            INSERT INTO publication_approval_events
                (batch_id, action, actor_user_id, actor_chat_id, detail)
            VALUES (%s, %s, %s, %s, 'telegram_callback')
            """,
            (parsed_id, normalized_action, str(actor_user_id or "")[:100], str(actor_chat_id or "")[:100]),
        )
    result = dict(updated or {})
    result["accepted"] = True
    return result


def telegram_update_offset() -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT state_value FROM telegram_bot_state WHERE state_key = 'update_offset'"
        ).fetchone()
    try:
        return max(0, int((row or {}).get("state_value") or 0))
    except (TypeError, ValueError):
        return 0


def set_telegram_update_offset(offset: int) -> None:
    value = max(0, int(offset))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot_state (state_key, state_value)
            VALUES ('update_offset', %s)
            ON CONFLICT (state_key) DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = now()
            """,
            (str(value),),
        )


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
        notify_telegram_approval(
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
        notify_telegram_approval(
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
    post = dict(row) if row else None
    # 공개 전 차단(FAILED)은 새 승인으로 재시도할 수 있어야 한다. 반대로 클릭이 시작된
    # PUBLISHING·PUBLISHED·PUBLISH_UNKNOWN은 결과가 확정될 때까지 항상 중복을 막는다.
    blocked = {"PUBLISHING", "PUBLISHED", "PUBLISH_UNKNOWN"}
    return {"exists": bool(post and str(post.get("status") or "") in blocked), "post": post}


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


def coupang_admin_overview() -> dict[str, Any]:
    """Return the compact operating snapshot used by the Coupang admin dashboard."""
    now = datetime.now(KOREA_TIMEZONE)
    today = now.date()
    schedule_hours = (7, 12, 18)
    next_run = None
    for hour in schedule_hours:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            next_run = candidate
            break
    if next_run is None:
        from datetime import timedelta
        next_run = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    with _connect() as conn:
        run_rows = conn.execute(
            """
            SELECT id, job_name, platform, status, step, product_id, product_name,
                   error_code, error_message, retry_count, started_at, finished_at, updated_at
            FROM automation_runs
            WHERE platform = 'coupang' AND (updated_at AT TIME ZONE 'Asia/Seoul')::date = %s
            ORDER BY updated_at DESC LIMIT 50
            """,
            (today,),
        ).fetchall()
        success = conn.execute(
            """
            SELECT product_name, product_id, naver_post_url, published_at
            FROM blog_posts
            WHERE platform = 'coupang' AND status = 'PUBLISHED' AND naver_post_url IS NOT NULL
            ORDER BY published_at DESC NULLS LAST LIMIT 1
            """
        ).fetchone()
        error = conn.execute(
            """
            SELECT product_name, step, error_message, updated_at
            FROM automation_runs
            WHERE platform = 'coupang' AND status IN ('FAILED', 'ERROR')
            ORDER BY updated_at DESC LIMIT 1
            """
        ).fetchone()
        queue_rows = conn.execute(
            """
            SELECT publish_state, COUNT(*) AS count
            FROM publication_approval_batches
            WHERE source = 'coupang-publish'
              AND publish_state IN ('NOT_STARTED', 'PUBLISHING')
            GROUP BY publish_state
            """
        ).fetchall()
    queue = {"NOT_STARTED": 0, "PUBLISHING": 0}
    for row in queue_rows:
        queue[str(row["publish_state"])] = int(row["count"])
    return {
        "today": today.isoformat(),
        "today_runs": [dict(row) for row in run_rows],
        "next_schedule": next_run.isoformat(),
        "recent_success": dict(success) if success else None,
        "recent_error": dict(error) if error else None,
        "queue": queue,
        "auto_publish": True,
    }


_recent_approval_notifications: dict[str, float] = {}
_APPROVAL_NOTIFICATION_DEDUPE_SECONDS = 300


def notify_telegram_approval(text: str) -> bool:
    """Send a result notice to the approval channel without exposing its identifier.

    Identical notices generated by overlapping workers or retry paths are suppressed
    for a short window so one product does not create duplicate Telegram alerts.
    """
    now = time.time()
    fingerprint = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    previous = _recent_approval_notifications.get(fingerprint)
    if previous is not None and now - previous < _APPROVAL_NOTIFICATION_DEDUPE_SECONDS:
        return True
    _recent_approval_notifications[fingerprint] = now
    for key, sent_at in list(_recent_approval_notifications.items()):
        if now - sent_at >= _APPROVAL_NOTIFICATION_DEDUPE_SECONDS:
            _recent_approval_notifications.pop(key, None)

    chat_id = active_telegram_approval_chat_id()
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": "true"}
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


def ensure_toss_share_link(
    taca_item_id: str,
    issuer: Callable[[str], dict[str, str]],
) -> dict[str, Any]:
    """Return a stored link or issue and persist exactly one link for a selected product option."""
    product_id = str(taca_item_id or "").strip()
    if not product_id.isdigit():
        raise ValueError("invalid Toss item ID")
    with _connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (product_id,))
        existing = conn.execute(
            "SELECT taca_item_id, short_url, origin_url, publisher_id, issued_at FROM toss_share_links WHERE taca_item_id = %s",
            (product_id,),
        ).fetchone()
        if existing:
            result = dict(existing)
            result["reused"] = True
            return result
        product = conn.execute(
            "SELECT taca_item_id, product_name, is_sold_out FROM toss_products WHERE taca_item_id = %s",
            (product_id,),
        ).fetchone()
        if not product:
            raise ValueError("수집된 토스 상품을 찾지 못했습니다.")
        if bool(product["is_sold_out"]):
            raise ValueError("품절 상품은 쉐어링크를 발급할 수 없습니다.")
        issued = issuer(product_id)
        issued_id = str(issued.get("taca_item_id") or "").strip()
        short_url = str(issued.get("short_url") or "").strip()
        origin_url = str(issued.get("origin_url") or "").strip()
        publisher_id = str(issued.get("publisher_id") or "").strip()
        if issued_id != product_id or not short_url.startswith("https://") or not publisher_id:
            raise ValueError("토스 쉐어링크 발급 응답을 검증하지 못했습니다.")
        row = conn.execute(
            """
            INSERT INTO toss_share_links (taca_item_id, short_url, origin_url, publisher_id)
            VALUES (%s, %s, %s, %s)
            RETURNING taca_item_id, short_url, origin_url, publisher_id, issued_at
            """,
            (product_id, short_url, origin_url, publisher_id),
        ).fetchone()
    result = dict(row or {})
    result["reused"] = False
    return result


def toss_product_with_share_link(taca_item_id: str) -> dict[str, Any] | None:
    item_id = str(taca_item_id or "").strip()
    if not item_id.isdigit():
        raise ValueError("invalid Toss item ID")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT p.taca_item_id, p.product_name, p.thumbnail_url, p.product_url,
                   p.display_price, p.is_sold_out, l.short_url, l.origin_url
            FROM toss_products p
            LEFT JOIN toss_share_links l ON l.taca_item_id = p.taca_item_id
            WHERE p.taca_item_id = %s
            """,
            (item_id,),
        ).fetchone()
    return dict(row) if row else None


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
