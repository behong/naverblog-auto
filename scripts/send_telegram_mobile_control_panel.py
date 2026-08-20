from __future__ import annotations

from telegram_approval import send_mobile_control_panel


def main() -> int:
    send_mobile_control_panel()
    print("MOBILE_CONTROL_PANEL_SENT=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
