from __future__ import annotations

from automation_store import activate_telegram_approval_chat_candidate


def main() -> int:
    if not activate_telegram_approval_chat_candidate():
        print("TELEGRAM_APPROVAL_CHANNEL_CANDIDATE_NOT_FOUND")
        return 1
    print("TELEGRAM_APPROVAL_CHANNEL_ACTIVATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
