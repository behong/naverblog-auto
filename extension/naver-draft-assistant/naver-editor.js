const PANEL_ID = "naver-draft-assistant-panel";
const PROBE_PREFIX = "__NAVER_DRAFT_PROBE__";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function createPanel() {
  let panel = document.getElementById(PANEL_ID);
  if (panel) return panel;
  panel = document.createElement("section");
  panel.id = PANEL_ID;
  panel.setAttribute("role", "status");
  panel.style.cssText = [
    "position:fixed", "right:20px", "bottom:20px", "z-index:2147483647",
    "width:330px", "padding:16px", "border-radius:14px",
    "background:#fff", "color:#1b1b1b", "box-shadow:0 12px 36px rgba(0,0,0,.24)",
    "font-family:Arial,'Malgun Gothic',sans-serif", "font-size:14px", "line-height:1.45",
    "border:1px solid #d9e2d9"
  ].join(";");
  document.documentElement.appendChild(panel);
  return panel;
}

function renderPanel({ title, text, tone = "info", actionLabel, onAction }) {
  const panel = createPanel();
  const color = tone === "error" ? "#b3261e" : tone === "success" ? "#087f23" : "#1273de";
  panel.innerHTML = `
    <div style="display:flex;gap:8px;align-items:flex-start">
      <strong style="color:${color}">네이버 초안 입력 도우미</strong>
      <span style="margin-left:auto;color:#777;font-size:12px">발행하지 않음</span>
    </div>
    <p style="margin:8px 0 12px">${escapeHtml(text)}</p>
    ${actionLabel ? `<button type="button" data-naver-draft-action style="width:100%;border:0;border-radius:8px;padding:10px 12px;background:${color};color:#fff;font-weight:700;cursor:pointer">${escapeHtml(actionLabel)}</button>` : ""}
    <p style="margin:10px 0 0;color:#666;font-size:12px">게시·저장·예약 버튼은 이 확장 프로그램이 조작하지 않습니다.</p>
  `;
  const button = panel.querySelector("[data-naver-draft-action]");
  if (button && onAction) button.addEventListener("click", onAction, { once: true });
}

function normalizeEditorText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function isTitlePlaceholderText(text) {
  return ["제목", "제목을 입력하세요.", "제목을 입력해 주세요."].includes(normalizeEditorText(text));
}

function isBodyPlaceholderText(text) {
  const normalized = normalizeEditorText(text);
  return [
    "나를 돌아보는 회고, 뜻밖의 발견을 기다립니다. #모두의회고",
    "내용을 입력하세요.",
    "본문을 입력하세요."
  ].includes(normalized);
}

function isEmptyEditorTarget(target, kind) {
  const value = getText(target);
  if (!value) return true;
  return kind === "title" ? isTitlePlaceholderText(value) : isBodyPlaceholderText(value);
}

function dispatchInput(target, inputType = "insertText") {
  target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType, data: null }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
}

function getText(target) {
  if (!target) return "";
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return target.value.trim();
  return (target.innerText || target.textContent || "").trim();
}

function setText(target, value) {
  target.focus();
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    target.value = value;
    dispatchInput(target);
    return getText(target) === value.trim();
  }

  const selection = target.ownerDocument.getSelection();
  const range = target.ownerDocument.createRange();
  range.selectNodeContents(target);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
  const inserted = target.ownerDocument.execCommand("insertText", false, value);
  if (!inserted) {
    target.textContent = value;
  }
  dispatchInput(target);
  return getText(target) === value.trim();
}

function clearText(target) {
  target.focus();
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    target.value = "";
  } else {
    target.ownerDocument.execCommand("selectAll", false, null);
    target.ownerDocument.execCommand("delete", false, null);
    if (getText(target)) target.textContent = "";
  }
  dispatchInput(target, "deleteContentBackward");
  return !getText(target);
}

function editorDocuments(root = document, visited = new Set()) {
  if (!root || visited.has(root)) return [];
  visited.add(root);
  const documents = [root];

  // SmartEditor ONE의 실제 제목·본문은 열린 Shadow DOM 안에 있을 수 있다.
  // 열린 루트만 읽으며 닫힌 Shadow DOM이나 교차 출처 프레임은 탐색하지 않는다.
  for (const host of root.querySelectorAll?.("*") || []) {
    if (host.shadowRoot) documents.push(...editorDocuments(host.shadowRoot, visited));
  }
  for (const frame of root.querySelectorAll?.("iframe") || []) {
    try {
      if (frame.contentDocument) documents.push(...editorDocuments(frame.contentDocument, visited));
    } catch {
      // Cross-origin frames are intentionally not inspected.
    }
  }
  return documents;
}

function targetRect(target) {
  return target?.getBoundingClientRect?.() || { width: 0, height: 0, top: Number.MAX_SAFE_INTEGER };
}

function isUsableTarget(target) {
  if (!target || target.disabled || target.getAttribute("aria-hidden") === "true") return false;
  if (target.closest?.("[aria-hidden='true']")) return false;
  const style = target.ownerDocument.defaultView?.getComputedStyle(target);
  if (!style || style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
  const rect = targetRect(target);
  // SmartEditor의 숨은 input_buffer는 작은 입력 요소이므로 실제 편집 영역만 허용한다.
  return rect.width >= 20 && rect.height >= 16;
}

function editableTarget(target) {
  if (!target) return null;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return target;
  if (target.isContentEditable || target.matches("[contenteditable]")) return target;
  return target.querySelector("[contenteditable]") || target.closest("[contenteditable]");
}

function firstMatching(documents, selectors, predicate = isUsableTarget) {
  for (const root of documents) {
    for (const selector of selectors) {
      for (const match of root.querySelectorAll(selector)) {
        const target = editableTarget(match);
        if (target && predicate(target)) return target;
      }
    }
  }
  return null;
}

function elementSignals(target) {
  return [
    target?.className, target?.id, target?.getAttribute?.("name"),
    target?.getAttribute?.("placeholder"), target?.getAttribute?.("aria-label"),
    target?.getAttribute?.("data-placeholder")
  ].filter(Boolean).join(" ").toLowerCase();
}

function hasTitleSignal(target) {
  return /제목|(^|[-_\s])title($|[-_\s])/.test(elementSignals(target));
}

function isUtilityTarget(target) {
  return /글감|검색|search|find|command/.test(elementSignals(target));
}

function isContentEditableTarget(target) {
  return Boolean(target?.isContentEditable || target?.matches?.("[contenteditable]"));
}

function collectEditableCandidates() {
  const candidates = [];
  for (const root of editorDocuments()) {
    for (const match of root.querySelectorAll("[contenteditable], textarea, input[type='text']")) {
      const target = editableTarget(match);
      if (!target || !isUsableTarget(target) || candidates.some((candidate) => candidate.target === target)) continue;
      const rect = targetRect(target);
      candidates.push({ target, rect, area: rect.width * rect.height });
    }
  }
  return candidates;
}

function findTitleTarget() {
  const documents = editorDocuments();
  const exact = firstMatching(documents, [
    "input[placeholder*='제목']", "textarea[placeholder*='제목']",
    "input[aria-label*='제목']", "textarea[aria-label*='제목']",
    ".se-title-text", ".se-title [contenteditable]",
    "[contenteditable][aria-label*='제목']", "[contenteditable][data-placeholder*='제목']",
    "[contenteditable][placeholder*='제목']"
  ]);
  if (exact) return exact;

  const candidates = collectEditableCandidates()
    .filter(({ target }) => !isUtilityTarget(target) && !isBodyPlaceholderText(getText(target)));
  candidates.sort((a, b) => {
    const aMarked = hasTitleSignal(a.target) || isTitlePlaceholderText(getText(a.target));
    const bMarked = hasTitleSignal(b.target) || isTitlePlaceholderText(getText(b.target));
    if (aMarked !== bMarked) return aMarked ? -1 : 1;
    if (a.rect.top !== b.rect.top) return a.rect.top - b.rect.top;
    return b.area - a.area;
  });
  return candidates[0]?.target || null;
}

function findBodyTarget() {
  const documents = editorDocuments();
  const title = findTitleTarget();
  const exact = firstMatching(documents, [
    "[contenteditable].se-editable", ".se-main-container [contenteditable]",
    ".se-component-content [contenteditable]", ".se-section-text [contenteditable]",
    "body[contenteditable]", "[role='textbox'][contenteditable]"
  ], (target) => isUsableTarget(target) && target !== title && !target.closest(".se-title"));
  if (exact) return exact;

  const candidates = collectEditableCandidates()
    .filter(({ target }) => target !== title && isContentEditableTarget(target) && !isUtilityTarget(target) && !target.closest(".se-title") && !hasTitleSignal(target));
  candidates.sort((a, b) => b.area - a.area || a.rect.top - b.rect.top);
  return candidates[0]?.target || null;
}

function isAttachableFileInput(input) {
  // 네이버의 사진 추가 input은 UI상 숨겨져 있을 수 있으므로 화면 크기로 제외하지 않는다.
  return Boolean(input && !input.disabled && input.getAttribute("aria-hidden") !== "true");
}

function findImageInput() {
  const inputs = editorDocuments().flatMap((root) => [...root.querySelectorAll("input[type='file']")]);
  const usableInputs = inputs.filter(isAttachableFileInput);
  const imageInput = usableInputs.find((input) => /image|사진/i.test(input.accept || ""));
  return imageInput || usableInputs[0] || null;
}

function editorDiagnostics() {
  const documents = editorDocuments();
  const editableCount = documents.reduce((count, root) => count + root.querySelectorAll("[contenteditable]").length, 0);
  const textInputCount = documents.reduce((count, root) => count + root.querySelectorAll("input, textarea").length, 0);
  const usableCount = collectEditableCandidates().length;
  return `탐지 문서 ${documents.length}개, 편집 가능 요소 ${editableCount}개, 입력 요소 ${textInputCount}개, 사용 가능 후보 ${usableCount}개`;
}

function safeAttribute(target, name) {
  return String(target?.getAttribute?.(name) || "").slice(0, 240);
}

async function editorDiagnosticReport() {
  const documents = editorDocuments();
  let linkApplicationTrace = null;
  let autoFillTrace = null;
  try {
    const traceResponse = await chrome.runtime.sendMessage({ type: "NAVER_GET_LINK_TRACE" });
    if (traceResponse?.ok) linkApplicationTrace = traceResponse.trace || null;
    const fillResponse = await chrome.runtime.sendMessage({ type: "NAVER_GET_AUTOFILL_TRACE" });
    if (fillResponse?.ok) autoFillTrace = fillResponse.trace || null;
  } catch {
    // 진단 본문은 현재 페이지 구조만으로도 유효하므로 추적 수신 실패는 무시한다.
  }
  const report = {
    reportType: "naver-draft-assistant-editor-structure",
    extensionVersion: chrome.runtime.getManifest().version,
    note: "제목·본문의 실제 텍스트, 로그인 정보, 쿠키, 파일 데이터는 포함하지 않습니다. 링크 추적에는 선택 문자열 길이와 버튼 구조만 포함합니다.",
    linkApplicationTrace,
    autoFillTrace,
    documents: documents.map((root, documentIndex) => {
      const targets = [...root.querySelectorAll("[contenteditable], textarea, input")].slice(0, 30);
      return {
        documentIndex,
        rootType: root instanceof ShadowRoot ? "shadow-root" : root instanceof Document ? "document" : "other",
        host: root instanceof ShadowRoot ? {
          tag: root.host?.tagName || "",
          id: String(root.host?.id || "").slice(0, 160),
          className: String(root.host?.className || "").slice(0, 240)
        } : null,
        targetCount: targets.length,
        targets: targets.map((match, index) => {
          const target = editableTarget(match) || match;
          const rect = targetRect(target);
          const parentRect = targetRect(target.parentElement);
          const style = target.ownerDocument.defaultView?.getComputedStyle(target);
          return {
            index,
            tag: target.tagName,
            type: safeAttribute(target, "type"),
            contenteditable: safeAttribute(target, "contenteditable"),
            id: String(target.id || "").slice(0, 240),
            className: String(target.className || "").slice(0, 360),
            role: safeAttribute(target, "role"),
            ariaLabel: safeAttribute(target, "aria-label"),
            placeholder: safeAttribute(target, "placeholder"),
            dataPlaceholder: safeAttribute(target, "data-placeholder"),
            accept: safeAttribute(target, "accept"),
            ownRect: { width: Math.round(rect.width), height: Math.round(rect.height), top: Math.round(rect.top) },
            parentRect: { width: Math.round(parentRect.width), height: Math.round(parentRect.height), top: Math.round(parentRect.top) },
            clientSize: { width: target.clientWidth || 0, height: target.clientHeight || 0 },
            offsetParentPresent: Boolean(target.offsetParent),
            computed: { display: style?.display || "", visibility: style?.visibility || "", opacity: style?.opacity || "" }
          };
        })
      };
    })
  };
  return JSON.stringify(report, null, 2);
}

async function copyEditorDiagnostics() {
  const report = await editorDiagnosticReport();
  await navigator.clipboard.writeText(report);
  return report.length;
}

async function runPreflight(titleTarget, bodyTarget) {
  if (!isEmptyEditorTarget(titleTarget, "title") || !isEmptyEditorTarget(bodyTarget, "body")) {
    throw new Error("기존 제목 또는 본문이 있어 덮어쓰지 않았습니다. 새 글쓰기 화면에서 다시 시도해 주세요.");
  }
  if (isTitlePlaceholderText(getText(titleTarget)) && !clearText(titleTarget)) {
    throw new Error("제목 기본 안내 문구를 원복하지 못했습니다.");
  }
  if (isBodyPlaceholderText(getText(bodyTarget)) && !clearText(bodyTarget)) {
    throw new Error("본문 기본 안내 문구를 원복하지 못했습니다.");
  }
  const probe = `${PROBE_PREFIX}${Date.now()}`;
  if (!setText(titleTarget, probe) || getText(titleTarget) !== probe) {
    throw new Error("제목 입력 검증에 실패했습니다.");
  }
  if (!clearText(titleTarget)) throw new Error("제목 테스트 문구를 원복하지 못했습니다.");
  if (!setText(bodyTarget, probe) || getText(bodyTarget) !== probe) {
    throw new Error("본문 입력 검증에 실패했습니다.");
  }
  if (!clearText(bodyTarget)) throw new Error("본문 테스트 문구를 원복하지 못했습니다.");
}

function findInputBufferTarget() {
  const candidates = [];
  for (const root of editorDocuments()) {
    const body = root.body;
    if (!body?.isContentEditable) continue;
    const rect = targetRect(body);
    // SmartEditor가 포커스된 제목·본문 값을 받는 내부 input_buffer 문서다.
    if (rect.width >= 300 && rect.height <= 4) candidates.push(body);
  }
  return candidates[0] || null;
}

function isAssistantPanelTarget(target) {
  return Boolean(target?.closest?.(`#${PANEL_ID}`));
}

function isInteractiveControl(target) {
  return Boolean(target?.closest?.("button, a, input, textarea, select, [role='button']"));
}

function waitForEditorClick(kind) {
  const label = kind === "title" ? "제목" : "본문";
  renderPanel({
    title: `${label} 클릭 필요`,
    text: `네이버 ${label} 칸을 한 번 직접 클릭해 주세요. 클릭 뒤 자동으로 ${label}만 입력하며, 저장·발행·예약은 실행하지 않습니다.`,
    tone: "info"
  });

  return new Promise((resolve, reject) => {
    let settled = false;
    // 제목·본문은 최상위 문서가 아닌 SmartEditor iframe/Shadow DOM 안에 있다.
    const eventRoots = editorDocuments();
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      for (const root of eventRoots) root.removeEventListener?.("pointerdown", onPointerDown, true);
      clearTimeout(timeoutId);
      callback(value);
    };
    const onPointerDown = (event) => {
      if (isAssistantPanelTarget(event.target) || isInteractiveControl(event.target)) return;
      // 네이버가 포커스를 갱신한 뒤에만 input_buffer를 읽는다.
      setTimeout(() => {
        const inputBuffer = findInputBufferTarget();
        if (inputBuffer) finish(resolve, inputBuffer);
      }, 180);
    };
    const timeoutId = setTimeout(() => {
      finish(reject, new Error(`${label} 칸 클릭을 확인하지 못했습니다. 새 글쓰기 화면에서 다시 시도해 주세요.`));
    }, 60000);
    for (const root of eventRoots) root.addEventListener?.("pointerdown", onPointerDown, true);
  });
}

function assertBlankInputBuffer(target, kind) {
  const current = getText(target);
  if (!current) return;
  throw new Error(`선택한 ${kind === "title" ? "제목" : "본문"} 칸에 기존 내용이 있어 덮어쓰지 않았습니다. 새 글쓰기 화면에서 다시 시도해 주세요.`);
}

function prepareInputBuffer(target) {
  target.focus();
  const selection = target.ownerDocument.getSelection();
  const range = target.ownerDocument.createRange();
  range.selectNodeContents(target);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function setInputBufferText(target, value) {
  prepareInputBuffer(target);
  const accepted = target.ownerDocument.execCommand("insertText", false, value);
  dispatchInput(target);
  // SmartEditor는 본문 반영 직후 input_buffer를 비울 수 있으므로 즉시 텍스트를 재읽지 않는다.
  return accepted;
}

function textLineToFragment(doc, line) {
  const fragment = doc.createDocumentFragment();
  const urlPattern = /(https?:\/\/[^\s<>]+)/g;
  let cursor = 0;
  for (const match of line.matchAll(urlPattern)) {
    const start = match.index || 0;
    if (start > cursor) fragment.appendChild(doc.createTextNode(line.slice(cursor, start)));
    const anchor = doc.createElement("a");
    anchor.href = match[0];
    anchor.textContent = match[0];
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    fragment.appendChild(anchor);
    cursor = start + match[0].length;
  }
  if (cursor < line.length) fragment.appendChild(doc.createTextNode(line.slice(cursor)));
  return fragment;
}

function setInputBufferParagraphs(target, value) {
  prepareInputBuffer(target);
  const doc = target.ownerDocument;
  const paragraphs = String(value || "")
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  if (!paragraphs.length) return false;

  const container = doc.createElement("div");
  paragraphs.forEach((paragraph, index) => {
    const block = doc.createElement("p");
    paragraph.split("\n").forEach((line, lineIndex) => {
      if (lineIndex) block.appendChild(doc.createElement("br"));
      block.appendChild(textLineToFragment(doc, line));
    });
    container.appendChild(block);
    if (index < paragraphs.length - 1) {
      // 주요 구역 사이에 실제 빈 문단 한 개를 넣는다.
      const spacer = doc.createElement("p");
      spacer.appendChild(doc.createElement("br"));
      container.appendChild(spacer);
    }
  });

  const accepted = doc.execCommand("insertHTML", false, container.innerHTML);
  dispatchInput(target);
  return accepted;
}

async function fillDraftWithInputBuffer(draft) {
  const titleBuffer = await waitForEditorClick("title");
  assertBlankInputBuffer(titleBuffer, "title");
  if (!setInputBufferText(titleBuffer, draft.title)) throw new Error("제목 입력 명령을 전달하지 못했습니다.");

  const bodyBuffer = await waitForEditorClick("body");
  assertBlankInputBuffer(bodyBuffer, "body");
  const bodyWithTags = draft.tags ? `${draft.body}\n\n${draft.tags}` : draft.body;
  if (!setInputBufferParagraphs(bodyBuffer, bodyWithTags)) throw new Error("본문 입력 명령을 전달하지 못했습니다.");

  return {
    ok: false,
    manualImage: true,
    reason: "원본 대표 이미지는 blogauto에서 ‘이미지 복사’를 누른 뒤 네이버 본문에서 Ctrl+V로 붙여넣어 주세요. 이미지가 실제로 보이기 전에는 발행하지 마세요."
  };
}

async function fillDraft(draft) {
  const titleTarget = findTitleTarget();
  const bodyTarget = findBodyTarget();
  if (!titleTarget || !bodyTarget) {
    return fillDraftWithInputBuffer(draft);
  }
  await runPreflight(titleTarget, bodyTarget);
  if (!setText(titleTarget, draft.title)) throw new Error("제목을 입력하지 못했습니다.");
  const bodyWithTags = draft.tags ? `${draft.body}\n\n${draft.tags}` : draft.body;
  if (!setText(bodyTarget, bodyWithTags)) throw new Error("본문을 입력하지 못했습니다.");
  return {
    ok: false,
    manualImage: true,
    reason: "원본 대표 이미지는 blogauto에서 ‘이미지 복사’를 누른 뒤 네이버 본문에서 Ctrl+V로 붙여넣어 주세요. 이미지가 실제로 보이기 전에는 발행하지 마세요."
  };
}

async function requestDraft() {
  const response = await chrome.runtime.sendMessage({ type: "NAVER_GET_DRAFT" });
  if (!response?.ok) throw new Error(response?.error || "초안을 불러오지 못했습니다.");
  return response.draft;
}

async function startAutomaticFill(draft) {
  renderPanel({
    title: "자동 입력 중",
    text: "제목·본문·원본 대표 이미지를 입력하고 있습니다. 저장·발행·예약·공개 상태는 변경하지 않습니다.",
    tone: "info"
  });
  try {
    const response = await chrome.runtime.sendMessage({ type: "NAVER_AUTO_FILL", draftId: draft.id });
    if (!response?.ok) throw new Error(response?.error || "자동 입력을 시작하지 못했습니다.");
    const report = response.report || {};
    const verificationNote = report.bodyVerificationLimited || report.imageVerificationLimited
      ? " 제목은 확인됐고, 본문·이미지는 네이버 내부 렌더링 특성상 화면에서 확인해 주세요."
      : " 제목·본문·이미지 반영 확인을 마쳤습니다.";
    renderPanel({
      title: "자동 입력 완료",
      text: `제목·본문·원본 대표 이미지 입력을 요청했습니다.${verificationNote} 발행은 직접 진행해 주세요.`,
      tone: "success",
      actionLabel: "비민감 진단 정보 복사",
      onAction: async (event) => {
        // DOM 이벤트의 currentTarget은 await 이후 null이 될 수 있으므로 즉시 보관한다.
        const button = event.currentTarget;
        if (!button) return;
        try {
          await copyEditorDiagnostics();
          if (!button.isConnected) return;
          button.textContent = "비민감 진단 정보 복사 완료";
          button.disabled = true;
          button.style.opacity = "0.72";
          button.style.cursor = "default";
        } catch {
          if (button.isConnected) button.textContent = "진단 복사 실패 · 다시 시도";
        }
      }
    });
  } catch (error) {
    renderPanel({
      title: "자동 입력 중단",
      text: error.message || "자동 입력 중 오류가 발생했습니다.",
      tone: "error",
      actionLabel: "비민감 진단 정보 복사",
      onAction: async (event) => {
        // DOM 이벤트의 currentTarget은 await 이후 null이 될 수 있으므로 즉시 보관한다.
        const button = event.currentTarget;
        if (!button) return;
        try {
          await copyEditorDiagnostics();
          if (!button.isConnected) return;
          button.textContent = "비민감 진단 정보 복사 완료";
          button.disabled = true;
          button.style.opacity = "0.72";
          button.style.cursor = "default";
          // 자동 입력 중단 사유는 그대로 화면에 남겨 사용자가 함께 확인할 수 있게 한다.
        } catch {
          if (button.isConnected) button.textContent = "진단 복사 실패 · 다시 시도";
        }
      }
    });
  }
}

async function waitForDraft() {
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const draft = await requestDraft();
    if (draft) return draft;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return null;
}

async function showDraftPrompt() {
  try {
    const draft = await waitForDraft();
    if (!draft) return;
    // 2번으로 연 네이버 글쓰기 탭에서는 추가 사용자 클릭 없이 자동 입력을 시작한다.
    setTimeout(() => startAutomaticFill(draft), 450);
  } catch {
    // This script also runs on non-editor Naver pages; silently do nothing there.
  }
}

showDraftPrompt();
