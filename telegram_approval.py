from __future__ import annotations

import hmac
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
    mobile_toss_status,
    resolve_publication_approval,
    set_publication_approval_expected_chat_id,
    set_publication_approval_message_id,
    set_mobile_toss_release_paused,
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
    source_label = "COUPANG" if "coupang" in str(source or "").lower() else "TOSS"
    lines = [
        ("🧪" if preflight_only else "📝") + f" [{source_label}] 블로그 발행 승인 요청",
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


MOBILE_CONTROL_ACTIONS = {"status", "schedule", "pause", "resume", "help"}


def _mobile_control_action(value: str) -> str | None:
    prefix, separator, action = str(value or "").partition(":")
    if prefix != "mc" or not separator or action not in MOBILE_CONTROL_ACTIONS:
        return None
    return action


def _mobile_status_text() -> str:
    status = mobile_toss_status()
    queue = status["queue"]
    release_state = "⏸ 보류" if status["release_paused"] else "▶️ 활성"
    return "\n".join(
        [
            f"📊 오늘 토스 발행 현황 · {status['date']}",
            "",
            f"완료: {queue['PUBLISHED']}건",
            f"대기: {queue['QUEUED']}건",
            f"진행: {queue['RELEASED']}건",
            f"공개 전 실패: {queue['FAILED_PRE_SUBMIT']}건",
            f"결과 확인 필요: {queue['PUBLISH_UNKNOWN']}건",
            f"자동 발행: {release_state}",
            "",
            "다음 초안 준비: 18:00 · 4건",
            "승인된 대기열은 20분 간격으로 1건씩 순차 처리됩니다.",
        ]
    )


def _mobile_schedule_text() -> str:
    return "\n".join(
        [
            "🗓 오늘 운영 일정",
            "",
            "07:00 · 토스 초안 4건 준비",
            "12:00 · 토스 초안 2건 준비",
            "18:00 · 토스 초안 4건 준비",
            "",
            "각 시간대의 준비가 끝나면 텔레그램 승인 요청이 도착합니다.",
            "승인된 항목만 20분 간격으로 한 건씩 발행합니다.",
        ]
    )


def _mobile_help_text() -> str:
    return "\n".join(
        [
            "💬 모바일 운영 도움말",
            "",
            "📊 오늘 현황: 완료·대기·진행·실패 상태를 확인합니다.",
            "🗓 오늘 일정: 다음 초안 준비와 승인 흐름을 확인합니다.",
            "⏸ 자동 발행 보류: 이미 승인된 후속 발행을 안전하게 멈춥니다.",
            "▶️ 자동 발행 재개: 기존 승인 항목의 20분 간격 해제를 다시 허용합니다.",
            "",
            "상품 공개는 별도의 텔레그램 승인 없이는 시작되지 않습니다.",
        ]
    )


def _mobile_control_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 오늘 현황", "callback_data": "mc:status"},
                {"text": "🗓 오늘 일정", "callback_data": "mc:schedule"},
            ],
            [
                {"text": "⏸ 자동 발행 보류", "callback_data": "mc:pause"},
                {"text": "▶️ 자동 발행 재개", "callback_data": "mc:resume"},
            ],
            [{"text": "💬 운영 도움말", "callback_data": "mc:help"}],
        ]
    }


def send_mobile_control_panel() -> None:
    _api(
        "sendMessage",
        {
            "chat_id": active_telegram_approval_chat_id(),
            "text": "📱 블로그 자동 발행 모바일 운영 패널\n아래 버튼으로 오늘 현황과 자동 발행 상태를 관리할 수 있습니다.",
            "reply_markup": json.dumps(_mobile_control_keyboard(), ensure_ascii=False, separators=(",", ":")),
            "disable_web_page_preview": "true",
        },
    )


def _handle_mobile_control(callback_id: str, chat_id: str, action: str) -> None:
    expected_chat_id = active_telegram_approval_chat_id()
    if not expected_chat_id or not hmac.compare_digest(chat_id, expected_chat_id):
        _answer_callback(callback_id, "허용된 승인 채널에서만 사용할 수 있습니다.")
        return
    if action == "status":
        _api("sendMessage", {"chat_id": chat_id, "text": _mobile_status_text(), "disable_web_page_preview": "true"})
        _answer_callback(callback_id, "오늘 현황을 보냈습니다.")
        return
    if action == "schedule":
        _api("sendMessage", {"chat_id": chat_id, "text": _mobile_schedule_text(), "disable_web_page_preview": "true"})
        _answer_callback(callback_id, "오늘 일정을 보냈습니다.")
        return
    if action == "pause":
        set_mobile_toss_release_paused(True)
        _api("sendMessage", {"chat_id": chat_id, "text": "⏸ 자동 발행을 보류했습니다. 이미 공개 완료된 글에는 영향이 없고, 다음 대기열 해제만 멈춥니다."})
        _answer_callback(callback_id, "자동 발행을 보류했습니다.")
        return
    if action == "resume":
        set_mobile_toss_release_paused(False)
        _api("sendMessage", {"chat_id": chat_id, "text": "▶️ 자동 발행을 재개했습니다. 기존 승인 항목만 다음 20분 해제 시각부터 순차 처리됩니다."})
        _answer_callback(callback_id, "자동 발행을 재개했습니다.")
        return
    _api("sendMessage", {"chat_id": chat_id, "text": _mobile_help_text(), "disable_web_page_preview": "true"})
    _answer_callback(callback_id, "운영 도움말을 보냈습니다.")


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
    callback_data = str(callback.get("data") or "")
    mobile_action = _mobile_control_action(callback_data)
    parsed = _callback_parts(callback_data)
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = callback.get("from") if isinstance(callback.get("from"), dict) else {}
    chat_id = str(chat.get("id") or "")
    user_id = str(sender.get("id") or "")
    if not callback_id or not chat_id:
        if callback_id:
            _answer_callback(callback_id, "유효하지 않은 요청입니다.")
        return
    if mobile_action:
        _handle_mobile_control(callback_id, chat_id, mobile_action)
        return
    if not parsed:
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
