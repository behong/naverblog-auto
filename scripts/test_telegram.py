from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path


def load_settings() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    settings: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip()
    return settings


settings = load_settings()
message = """🧪 [네이버 블로그 자동화 연결 테스트]

상태: 텔레그램 알림 연결 정상
서비스: naverblog-auto
저장소: PostgreSQL 연결 완료

실제 오류 발생 시 상품명, 실패 단계, 재시도 횟수와 필요한 조치를 알려드립니다."""
data = urllib.parse.urlencode(
    {
        "chat_id": settings["TELEGRAM_CHAT_ID"],
        "text": message,
        "disable_web_page_preview": "true",
    }
).encode("utf-8")
request = urllib.request.Request(
    f"https://api.telegram.org/bot{settings['TELEGRAM_BOT_TOKEN']}/sendMessage",
    data=data,
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    result = json.load(response)
print(f"Telegram UTF-8 test sent: message_id={result['result']['message_id']}")
