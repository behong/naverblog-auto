from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The script can run directly inside the Docker image as `python scripts/...`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from toss_collector import COLLECTION_SOURCES, collect_toss_listing
from toss_open_api import TossOpenApiError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one documented Toss Sharelink product-list page into PostgreSQL."
    )
    parser.add_argument(
        "--source",
        choices=sorted(COLLECTION_SOURCES),
        default="best-selling",
        help="Toss Open API listing to collect.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=30,
        help="Requested item count; best-selling supports 1–100 and today-deals 1–30.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = collect_toss_listing(args.source, args.size)
    except TossOpenApiError as exc:
        print(json.dumps({"ok": False, "source": args.source, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
