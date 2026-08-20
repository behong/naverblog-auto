"""Print non-sensitive extension heartbeat freshness without exposing device identifiers or tokens."""

from automation_store import _connect


def main() -> None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE enabled) AS enabled_device_count,
                COALESCE(
                    FLOOR(EXTRACT(EPOCH FROM (now() - MAX(last_seen_at) FILTER (WHERE enabled))))::bigint,
                    -1
                ) AS freshest_seen_seconds_ago
            FROM extension_devices
            """
        ).fetchone()
    print(f"ENABLED_DEVICE_COUNT={int(row['enabled_device_count'] or 0)}")
    print(f"FRESHEST_DEVICE_SECONDS_AGO={int(row['freshest_seen_seconds_ago'])}")


if __name__ == "__main__":
    main()
