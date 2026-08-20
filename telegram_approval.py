from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from automation_store import (
    TELEGRAM_BOT_TOKEN,
    active_telegram_approval_chat_id,
    create_publication_approval_batch,
    resolve_publication_approval,
    set_publication_approval_expected_chat_id,
    set_publication_approval_message_id,
    set_telegram_approval_chat_candidate,
    set_telegram_update_offset,
    telegram_update_offset,
)

APPROVAL_TTL_MINUTES = min(
    max(int(os.getenv("TELEGRAM_APPROVAL_TTL_MINUTES", "30")), 5), 120
)
POLL_TIMEOUT_SECONDS = 25


def configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and active_telegram_approval_chat_id())


def _api(method: str, payload: dict[str, Any] | None = None, timeout: int = 15) -> Any:
    if not configured():
        raise RuntimeError("Telegram approval is not configured")
    data = urllib.parse.urlencode(payload or {}, encoding="utf-8", errors="strict").encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Telegram Bot API 요청에 실패했습니다.") from exc
    if not isinstance(decoded, dict) or not decoded.get("ok"):
        raise RuntimeError("Telegram Bot API 요청이 거절됐습니다.")
    return decoded.get("result")


def _brief_item(item: dict[str, Any], index: int) -> str:
    name = " ".join(str(item.get("product_name") or item.get("name") or "상품명 없음").split())[:90]
    price = item.get("display_price") or item.get("price")
    try:
        price_text = f" · {int(price):,}원" if price not in (None, "") else ""
    except (TypeError, ValueError):
        price_text = ""
    return f"{index}. {name}{price_text}"


def send_publication_approval(
    summary: list[dict[str, Any]],
    source: str = "toss-daily",
    ttl_minutes: int | None = None,
) -> dict[str, Any]:
    """Create an approval batch and send one Telegram inline keyboard."""
    ttl = APPROVAL_TTL_MINUTES if ttl_minutes is None else min(max(int(ttl_minutes), 5), 120)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    batch = create_publication_approval_batch(summary, expires_at, source)
    batch_id = str(batch["id"])
    preflight_only = str(source or "") == "toss-preflight"
    lines = [
        "🧪 네이버 입력 사전 검증 승인 요청" if preflight_only else "📝 블로그 발행 승인 요청",
        f"준비된 글: {int(batch['item_count'])}건",
        "",
        *[_brief_item(item, index) for index, item in enumerate(summary, start=1)],
        "",
        "가격·링크·원본 이미지·중복 검증을 통과한 항목만 포함됩니다.",
        f"승인 유효 시간: {ttl}분",
        "승인 후 제목·본문·일반 링크·원본 이미지만 확인하며 발행 버튼은 누르지 않습니다." if preflight_only else "승인 후에도 실제 공개 전송 전 최종 재검증을 수행합니다.",
    ]
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"✅ {int(batch['item_count'])}건 승인", "callback_data": f"pa:{batch_id}:A"},
                {"text": "⏸ 보류", "callback_data": f"pa:{batch_id}:H"},
            ]
        ]
    }
    result = _api(
        "sendMessage",
        {
            "chat_id": active_telegram_approval_chat_id(),
            "text": "\n".join(lines),
            "reply_markup": json.dumps(keyboard, ensure_ascii=False, separators=(",", ":")),
            "disable_web_page_preview": "true",
        },
    )
    message_id = int(result.get("message_id") or 0)
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    actual_chat_id = str(chat.get("id") or "").strip()
    if message_id <= 0 or not actual_chat_id:
        raise RuntimeError("Telegram 승인 메시지 식별자 또는 채팅 정보를 받지 못했습니다.")
    set_publication_approval_expected_chat_id(batch_id, actual_chat_id)
    set_publication_approval_message_id(batch_id, message_id)
    return {**batch, "telegram_message_id": message_id, "expected_chat_id": actual_chat_id}


def _callback_parts(value: str) -> tuple[str, str] | None:
    parts = str(value or "").split(":")
    if len(parts) != 3 or parts[0] != "pa" or parts[2] not in {"A", "H"}:
        return None
    return parts[1], "APPROVED" if parts[2] == "A" else "HELD"


def _answer_callback(callback_id: str, text: str) -> None:
    _api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]}, timeout=10)


def _disable_buttons(chat_id: str, message_id: int) -> None:
    try:
        _api(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": str(message_id), "reply_markup": json.dumps({})},
            timeout=10,
        )
    except RuntimeError:
        return


def handle_update(update: dict[str, Any]) -> None:
    membership = update.get("my_chat_member")
    if isinstance(membership, dict):
        chat = membership.get("chat") if isinstance(membership.get("chat"), dict) else {}
        status = membership.get("new_chat_member") if isinstance(membership.get("new_chat_member"), dict) else {}
        if str(status.get("status") or "") in {"member", "administrator"}:
            set_telegram_approval_chat_candidate(str(chat.get("id") or ""))
        return
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return
    callback_id = str(callback.get("id") or "")
    parsed = _callback_parts(str(callback.get("data") or ""))
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = callback.get("from") if isinstance(callback.get("from"), dict) else {}
    chat_id = str(chat.get("id") or "")
    user_id = str(sender.get("id") or "")
    if not callback_id or not parsed or not chat_id:
        if callback_id:
            _answer_callback(callback_id, "유효하지 않은 승인 요청입니다.")
        return
    batch_id, action = parsed
    try:
        result = resolve_publication_approval(batch_id, action, chat_id, user_id)
    except (RuntimeError, ValueError):
        _answer_callback(callback_id, "승인 처리 중 오류가 발생했습니다.")
        return
    if not result.get("accepted"):
        reason = str(result.get("reason") or "resolved")
        message_text = {
            "unexpected_chat": "허용된 채팅에서만 승인할 수 있습니다.",
            "expired": "승인 시간이 만료됐습니다.",
            "not_found": "승인 배치를 찾지 못했습니다.",
        }.get(reason, "이미 처리된 승인 요청입니다.")
        _answer_callback(callback_id, message_text)
        return
    count = int(result.get("item_count") or 0)
    confirmation = f"{count}건 발행 배치를 승인했습니다." if action == "APPROVED" else "발행 배치를 보류했습니다."
    _answer_callback(callback_id, confirmation)
    message_id = int(message.get("message_id") or 0)
    if message_id > 0:
        _disable_buttons(chat_id, message_id)


def poll_once() -> None:
    offset = telegram_update_offset()
    updates = _api(
        "getUpdates",
        {
            "offset": str(offset),
            "timeout": str(POLL_TIMEOUT_SECONDS),
            "allowed_updates": json.dumps(["callback_query", "my_chat_member"]),
        },
        timeout=POLL_TIMEOUT_SECONDS + 10,
    )
    if not isinstance(updates, list):
        return
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id") or 0)
        if update_id <= 0:
            continue
        handle_update(update)
        set_telegram_update_offset(update_id + 1)


def start_polling(stop_event: threading.Event) -> threading.Thread | None:
    if not configured():
        return None

    def run() -> None:
        while not stop_event.is_set():
            try:
                poll_once()
            except RuntimeError:
                stop_event.wait(5)

    worker = threading.Thread(target=run, name="telegram-approval-poller", daemon=True)
    worker.start()
    return worker
