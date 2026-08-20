from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


def korea_today() -> date:
    """Return the business date for scheduled publishing in Korea Standard Time."""
    return datetime.now(KOREA_TIMEZONE).date()
