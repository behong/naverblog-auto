from __future__ import annotations

"""토스 예약 실행에 필요한 모듈만 로드하는 컨테이너 빌드 점검.

이 스크립트는 수집·DB 쓰기·텔레그램 발송·네이버 발행을 수행하지 않는다.
"""

from app import build_admin_toss_draft
from automation_store import _connect, create_scheduled_toss_publish_items
from kst_time import korea_today
from telegram_approval import send_publication_approval
from toss_collector import collect_toss_listing


if __name__ == "__main__":
    _ = (
        build_admin_toss_draft,
        _connect,
        create_scheduled_toss_publish_items,
        korea_today,
        send_publication_approval,
        collect_toss_listing,
    )
    print("toss_schedule_runtime_imports=ok")
