from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.coupang_detail import CoupangDetailVerificationError, fetch_coupang_detail, merge_partner_link_with_detail


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Coupang product details without creating a post or approval batch.")
    parser.add_argument("--input", required=True, help="Path to a review-only partner-link batch JSON")
    parser.add_argument("--output", required=True, help="Path to a detail-review JSON")
    parser.add_argument("--max-items", type=int, default=1, help="Maximum records to fetch; 0 means all records")
    parser.add_argument("--delay-seconds", type=float, default=0.5, help="Delay between public product detail requests")
    args = parser.parse_args()

    values = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = values.get("records") if isinstance(values, dict) and isinstance(values.get("records"), list) else []
    if args.max_items > 0:
        records = records[: args.max_items]
    verified = []
    failures = []
    for index, record in enumerate(records):
        item = record if isinstance(record, dict) else {}
        try:
            detail = fetch_coupang_detail(str(item.get("product_url") or ""))
            verified.append(merge_partner_link_with_detail(item, detail))
        except (CoupangDetailVerificationError, OSError, ValueError) as exc:
            failures.append({"product_name": str(item.get("product_name") or f"후보 {index + 1}"), "reason": str(exc)})
        if index + 1 < len(records) and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    payload = {
        "source": "coupang-public-product-detail-review",
        "approval_only": True,
        "publish_executed": False,
        "summary": {"input": len(records), "verified": len(verified), "failed": len(failures)},
        "records": verified,
        "failures": failures,
    }
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "approval_only": True, "summary": payload["summary"], "output": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
