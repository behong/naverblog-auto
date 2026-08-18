from __future__ import annotations

"""Run the Naver editor safety gate from the user's own Windows machine.

This command opens only a fresh Naver writing tab, performs the keyboard-input
probe, removes its test text, stores a redacted run record through the existing
local API, and closes only the tab it opened.  It cannot select products, generate
affiliate links, upload images, create a draft, or publish a post.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from automation.editor_preflight import EditorPreflightError, verify_editor_input

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAVER_WRITE_URL = "https://blog.naver.com/GoBlogWrite.naver"


def load_local_env(path: Path) -> None:
    """Load unset key/value pairs from local .env without printing any value."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _post_run(payload: dict[str, object]) -> None:
    base_url = os.getenv("AUTOMATION_API_URL", "http://127.0.0.1:8765").rstrip("/")
    token = os.getenv("AUTOMATION_API_TOKEN", "").strip()
    if not token:
        return
    request = urllib.request.Request(
        f"{base_url}/api/automation/runs",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, TimeoutError):
        # The preflight result itself remains visible locally; never print a token
        # or retry indefinitely when the local history service is unavailable.
        return


@contextmanager
def browser_context() -> Iterator[tuple[BrowserContext, bool]]:
    """Yield a local persistent context or a CDP context.

    The bool means the context belongs to an already-running browser and must not
    be closed.  CDP mode is for a user-started Chrome session; profile mode starts
    a dedicated reusable automation profile.  Neither mode reads credentials.
    """
    cdp_url = os.getenv("AUTOMATION_CDP_URL", "").strip()
    with sync_playwright() as playwright:
        if cdp_url:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            try:
                yield context, True
            finally:
                browser.close()
            return

        executable = os.getenv("AUTOMATION_BROWSER_EXECUTABLE", "").strip() or None
        user_data_dir = Path(
            os.getenv("AUTOMATION_USER_DATA_DIR", str(PROJECT_ROOT / "data" / "browser-profile"))
        )
        headless = os.getenv("AUTOMATION_HEADLESS", "false").strip().lower() in {"1", "true", "yes"}
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            executable_path=executable,
            headless=headless,
            locale="ko-KR",
            viewport={"width": 1440, "height": 1100},
        )
        try:
            yield context, False
        finally:
            context.close()


def _logged_out(page: Page) -> bool:
    text = (page.locator("body").inner_text(timeout=5_000) or "")[:2_000]
    return "로그인" in text and "글쓰기" not in text


def _wait_for_manual_login(page: Page) -> None:
    """Keep the visible browser open for a user-owned, manual login.

    No username, password, cookie, or authentication form value is read.  The
    process only waits for the login screen to disappear, then reloads the Naver
    writing URL and continues with the non-publishing input preflight.
    """
    timeout_seconds = max(30, int(os.getenv("NAVER_LOGIN_WAIT_SECONDS", "300")))
    deadline = time.monotonic() + timeout_seconds
    print(
        "WAITING_FOR_NAVER_LOGIN: Sign in manually in the opened browser. "
        f"The safety check will continue automatically for up to {timeout_seconds} seconds.",
        flush=True,
    )
    while time.monotonic() < deadline:
        if page.is_closed():
            raise EditorPreflightError("로그인 대기 중 브라우저 탭이 닫혔습니다.")
        try:
            if not _logged_out(page):
                page.goto(NAVER_WRITE_URL, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1_000)
                if not _logged_out(page):
                    return
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1_000)
    raise EditorPreflightError("네이버 로그인 대기 시간이 초과되었습니다.")


def run() -> int:
    load_local_env(PROJECT_ROOT / ".env")
    run_id = str(uuid.uuid4())
    started = {
        "run_id": run_id,
        "job_name": "naver-editor-preflight",
        "platform": "toss",
        "status": "STARTED",
        "step": "네이버 스마트에디터 사전 검증 시작",
        "retry_count": 0,
        "context": {"mode": "preflight_only"},
    }
    _post_run(started)
    page: Page | None = None
    keep_browser = False
    try:
        with browser_context() as (context, keep_browser):
            page = context.new_page()
            page.goto(NAVER_WRITE_URL, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(1_500)
            if _logged_out(page):
                _wait_for_manual_login(page)
            result = verify_editor_input(page)
            _post_run(
                {
                    **started,
                    "status": "PRICE_VERIFIED",
                    "step": "네이버 스마트에디터 사전 검증 통과",
                    "context": {"mode": "preflight_only", "preflight": result.to_dict()},
                }
            )
            print(json.dumps({"ok": True, "preflight": result.to_dict()}, ensure_ascii=False))
            return 0
    except Exception as exc:
        _post_run(
            {
                **started,
                "status": "EDITOR_FAILED",
                "step": "네이버 스마트에디터 사전 검증",
                "error_code": "EDITOR_PREFLIGHT_FAILED",
                "error_message": str(exc),
                "retry_count": 0,
                "context": {
                    "mode": "preflight_only",
                    "required_action": "네이버 로그인 상태와 SmartEditor 화면을 확인하세요. 제목·본문 자동 입력 검증이 통과할 때까지 발행을 중단하세요.",
                },
            }
        )
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        # CDP mode intentionally leaves the user browser running.  In persistent
        # mode closing the context closes only the automation browser process while
        # retaining its session in AUTOMATION_USER_DATA_DIR.
        _ = keep_browser


def main() -> None:
    parser = argparse.ArgumentParser(description="Naver SmartEditor safe input preflight")
    parser.parse_args()
    raise SystemExit(run())


if __name__ == "__main__":
    main()
