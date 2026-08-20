from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_NOT_CONFIGURED")
        return 2
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getWebhookInfo",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        print("TELEGRAM_WEBHOOK_STATUS_UNAVAILABLE")
        return 1
    result = payload.get("result") if isinstance(payload, dict) else None
    if not payload.get("ok") or not isinstance(result, dict):
        print("TELEGRAM_WEBHOOK_STATUS_UNAVAILABLE")
        return 1
    url = str(result.get("url") or "")
    pending = int(result.get("pending_update_count") or 0)
    print("TELEGRAM_WEBHOOK_CONFIGURED" if url else "TELEGRAM_WEBHOOK_NOT_CONFIGURED")
    print(f"TELEGRAM_PENDING_UPDATES={pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
