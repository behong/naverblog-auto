from __future__ import annotations

import json
from automation_store import release_next_scheduled_toss_item, scheduled_toss_queue_status
from kst_time import korea_today


def main() -> int:
    today = korea_today()
    result = release_next_scheduled_toss_item(today)
    result["queue"] = scheduled_toss_queue_status(today)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
