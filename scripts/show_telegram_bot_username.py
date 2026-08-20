from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_NOT_CONFIGURED")
        return 2
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getMe",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        print("TELEGRAM_BOT_IDENTITY_UNAVAILABLE")
        return 1
    result = payload.get("result") if isinstance(payload, dict) else None
    username = str(result.get("username") or "") if isinstance(result, dict) else ""
    if not payload.get("ok") or not username:
        print("TELEGRAM_BOT_IDENTITY_UNAVAILABLE")
        return 1
    print(f"TELEGRAM_BOT_USERNAME=@{username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
