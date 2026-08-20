from __future__ import annotations

from automation_store import release_latest_extension_claim_for_retry


def main() -> int:
    released = release_latest_extension_claim_for_retry()
    print(f"APPROVED_DRAFT_RELEASED_FOR_RETRY={released}")
    return 0 if released else 1


if __name__ == "__main__":
    raise SystemExit(main())
