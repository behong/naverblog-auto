from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.coupang_goldbox import normalize_goldbox_candidates, to_review_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a review-only Coupang Goldbox candidate file.")
    parser.add_argument("--input", required=True, help="Path to the collector JSON file")
    parser.add_argument("--output", required=True, help="Path to the review JSON file")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else []
    previews, summary = normalize_goldbox_candidates(raw_candidates if isinstance(raw_candidates, list) else [])
    review = to_review_payload(previews, summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "review_only": True, "summary": summary, "output": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
