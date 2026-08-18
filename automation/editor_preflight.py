from __future__ import annotations

"""Naver SmartEditor input preflight.

This module deliberately has no publish capability.  It opens a fresh post editor,
proves that both title and body accept keyboard input without a human click, removes
all probe text, and returns a structured result.  Any ambiguous result is a hard
failure: callers must stop before product selection, affiliate-link creation,
image upload, or publishing.
"""

from dataclasses import asdict, dataclass
from typing import Literal
from uuid import uuid4

from playwright.sync_api import Frame, Locator, Page, TimeoutError as PlaywrightTimeoutError


Section = Literal["title", "body"]

TITLE_SELECTORS = (
    'textarea[aria-label*="제목"]',
    'input[aria-label*="제목"]',
    'textarea[placeholder*="제목"]',
    'input[placeholder*="제목"]',
    '[contenteditable="true"][aria-label*="제목"]',
    '[contenteditable="true"][data-placeholder*="제목"]',
    '[contenteditable="true"][placeholder*="제목"]',
)
BODY_SELECTORS = (
    '[contenteditable="true"][role="textbox"]',
    '[contenteditable="true"]',
    'textarea[aria-label*="본문"]',
    'textarea[placeholder*="본문"]',
)


class EditorPreflightError(RuntimeError):
    """The page did not prove that keyboard input reaches the intended editor."""


@dataclass(frozen=True)
class ProbeResult:
    section: Section
    selector: str
    frame_url: str
    active_chain: list[dict[str, str]]
    inserted: bool
    removed: bool


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    title: ProbeResult
    body: ProbeResult

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_visible(locator: Locator) -> bool:
    try:
        return locator.is_visible(timeout=800)
    except PlaywrightTimeoutError:
        return False


def _first_editable_candidate(page: Page, section: Section) -> tuple[Frame, str, Locator]:
    selectors = TITLE_SELECTORS if section == "title" else BODY_SELECTORS
    # Direct page candidates first, then same-origin editor frames.  Frames whose
    # DOM cannot be inspected are intentionally skipped instead of bypassed.
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector).first
            if not _is_visible(locator):
                continue
            try:
                if locator.is_editable(timeout=800):
                    return frame, selector, locator
            except PlaywrightTimeoutError:
                continue
    raise EditorPreflightError(f"{section} 입력 대상을 찾지 못했습니다.")


def _value_or_text(locator: Locator) -> str:
    tag_name = locator.evaluate("element => element.tagName.toLowerCase()")
    if tag_name in {"input", "textarea"}:
        return locator.input_value()
    return locator.text_content() or ""


def _active_chain(page: Page) -> list[dict[str, str]]:
    # Record only tag/id/class metadata.  No credentials or editor content is read.
    return page.evaluate(
        """() => {
            const chain = [];
            let doc = document;
            for (let depth = 0; depth < 8; depth += 1) {
              const el = doc.activeElement;
              if (!el) break;
              chain.push({
                tag: String(el.tagName || ''),
                id: String(el.id || ''),
                name: String(el.getAttribute?.('name') || ''),
                className: String(el.className || '').slice(0, 160),
              });
              if (el.tagName !== 'IFRAME') break;
              try {
                doc = el.contentDocument;
              } catch (_) {
                break;
              }
              if (!doc) break;
            }
            return chain;
        }"""
    )


def _focus_without_click(locator: Locator) -> None:
    """Focus an editable node and place a collapsed caret at the end.

    Calling focus() is intentional.  The routine must succeed without synthetic
    mouse clicks because a click-only path is the defect this guard is designed to
    detect.  It never assigns innerHTML/value or uses locator.fill().
    """
    locator.evaluate(
        """element => {
            element.focus({preventScroll: true});
            if (element.isContentEditable) {
              const selection = element.ownerDocument.getSelection();
              const range = element.ownerDocument.createRange();
              range.selectNodeContents(element);
              range.collapse(false);
              selection.removeAllRanges();
              selection.addRange(range);
            } else if (typeof element.setSelectionRange === 'function') {
              const length = String(element.value || '').length;
              element.setSelectionRange(length, length);
            }
        }"""
    )


def _contains_probe(locator: Locator, probe: str) -> bool:
    return probe in _value_or_text(locator)


def _clear_probe_with_keyboard(page: Page, locator: Locator, probe: str) -> bool:
    # Verify the exact text before deleting.  If the editor transformed the probe
    # in any way, preserve the page and fail instead of attempting broad deletion.
    current = _value_or_text(locator)
    if probe not in current:
        return False
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(150)
    return probe not in _value_or_text(locator)


def _probe_section(page: Page, section: Section) -> ProbeResult:
    frame, selector, locator = _first_editable_candidate(page, section)
    initial = _value_or_text(locator).strip()
    if initial:
        raise EditorPreflightError(
            f"{section} 입력 칸이 비어 있지 않아 안전상 사전 검증을 중단했습니다."
        )

    probe = f"__NAVER_AUTO_PROBE_{section.upper()}_{uuid4().hex}__"
    _focus_without_click(locator)
    active_chain = _active_chain(page)
    try:
        page.keyboard.type(probe, delay=8)
        page.wait_for_timeout(200)
        inserted = _contains_probe(locator, probe)
        removed = _clear_probe_with_keyboard(page, locator, probe) if inserted else False
    except PlaywrightTimeoutError as exc:
        raise EditorPreflightError(f"{section} 테스트 입력이 시간 초과했습니다.") from exc

    if not inserted or not removed or _value_or_text(locator).strip():
        raise EditorPreflightError(
            f"{section} 무인 입력 또는 삭제·원복 검증에 실패했습니다."
        )
    return ProbeResult(
        section=section,
        selector=selector,
        frame_url=frame.url,
        active_chain=active_chain,
        inserted=inserted,
        removed=removed,
    )


def verify_editor_input(page: Page) -> PreflightResult:
    """Run the mandatory title/body gate on a freshly opened Naver post editor.

    The caller must navigate to a new, blank editor page first.  A successful
    result is valid only for the currently open page and current browser session;
    the workflow should run it at the beginning of every scheduled job.
    """
    title = _probe_section(page, "title")
    body = _probe_section(page, "body")
    return PreflightResult(ok=True, title=title, body=body)
