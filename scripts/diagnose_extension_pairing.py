from __future__ import annotations

from automation_store import _connect


def main() -> int:
    with _connect() as conn:
        device = conn.execute(
            "SELECT count(*) AS count, max(last_seen_at) AS last_seen_at FROM extension_devices WHERE enabled = true"
        ).fetchone()
        batch = conn.execute(
            """
            SELECT status, extension_claimed_at IS NOT NULL AS claimed
            FROM publication_approval_batches
            ORDER BY decided_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """
        ).fetchone()
    print(f"EXTENSION_DEVICE_COUNT={int((device or {}).get('count') or 0)}")
    print(f"EXTENSION_DEVICE_LAST_SEEN={bool((device or {}).get('last_seen_at'))}")
    print(f"LATEST_APPROVAL_STATUS={str((batch or {}).get('status') or '')}")
    print(f"LATEST_APPROVAL_CLAIMED={bool((batch or {}).get('claimed'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
