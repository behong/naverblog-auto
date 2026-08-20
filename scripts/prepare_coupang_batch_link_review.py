from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.coupang_partner_link import parse_coupang_batch_link_results, to_batch_review_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a review-only Coupang partner-link batch.")
    parser.add_argument("--input", required=True, help="Path to a collector batch-result JSON file")
    parser.add_argument("--output", required=True, help="Path to a review JSON file")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    records, failures, summary = parse_coupang_batch_link_results(json.loads(input_path.read_text(encoding="utf-8")))
    payload = to_batch_review_payload(records, failures, summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "approval_only": True, "summary": summary, "output": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
