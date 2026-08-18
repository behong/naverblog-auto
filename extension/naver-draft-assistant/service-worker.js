const DRAFT_KEY = "pendingNaverDraft";
const DRAFT_TTL_MS = 10 * 60 * 1000;
const BLOGAUTO_ORIGIN = "https://blogauto.hongzi.us";
const DEBUGGER_VERSION = "1.3";
const LINK_TRACE_KEY = "naverDraftAssistantLinkTrace";
const AUTOFILL_TRACE_KEY = "naverDraftAssistantAutoFillTrace";

chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

function asText(value, maxLength) {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, maxLength);
}

function safeImageUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    if (url.origin !== BLOGAUTO_ORIGIN || !url.pathname.startsWith("/api/image")) return "";
    return url.href;
  } catch {
    return "";
  }
}

function isBlogAutoSender(sender) {
  try {
    return new URL(sender.url || sender.tab?.url || "").origin === BLOGAUTO_ORIGIN;
  } catch {
    return false;
  }
}

function isNaverEditorSender(sender) {
  try {
    const url = new URL(sender.url || sender.tab?.url || "");
    return (url.hostname === "blog.naver.com" || url.hostname === "m.blog.naver.com") &&
      /GoBlogWrite|Redirect=Write|PostWrite/i.test(url.href);
  } catch {
    return false;
  }
}

function normalizeDraft(rawDraft) {
  const title = asText(rawDraft?.title, 300);
  const body = asText(rawDraft?.body, 20_000);
  const tags = asText(rawDraft?.tags, 2_000);
  if (!title || !body) throw new Error("제목 또는 본문이 비어 있습니다.");
  return {
    id: crypto.randomUUID(),
    title,
    body,
    tags,
    imageUrl: safeImageUrl(rawDraft?.imageUrl),
    createdAt: Date.now(),
    expiresAt: Date.now() + DRAFT_TTL_MS,
  };
}

async function getLiveDraft() {
  const { [DRAFT_KEY]: draft } = await chrome.storage.session.get(DRAFT_KEY);
  if (!draft || !draft.expiresAt || draft.expiresAt < Date.now()) {
    await chrome.storage.session.remove(DRAFT_KEY);
    return null;
  }
  return draft;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function recordAutoFillTrace(patch) {
  const stored = await chrome.storage.session.get(AUTOFILL_TRACE_KEY);
  const previous = stored[AUTOFILL_TRACE_KEY] || {};
  await chrome.storage.session.set({
    [AUTOFILL_TRACE_KEY]: { ...previous, ...patch, updatedAt: Date.now() }
  });
}

async function send(tabId, method, params = {}) {
  return chrome.debugger.sendCommand({ tabId }, method, params);
}

async function click(tabId, point) {
  const payload = { x: Math.round(point.x), y: Math.round(point.y), button: "left", clickCount: 1 };
  await send(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", buttons: 1, ...payload });
  await send(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", buttons: 0, ...payload });
}

async function pressEnter(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13
  });
}

async function pressTab(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9
  });
}

async function pressDelete(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46, nativeVirtualKeyCode: 46
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46, nativeVirtualKeyCode: 46
  });
}

async function pressShiftHome(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Shift", code: "ShiftLeft", windowsVirtualKeyCode: 16, nativeVirtualKeyCode: 16
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Home", code: "Home", windowsVirtualKeyCode: 36, nativeVirtualKeyCode: 36, modifiers: 8
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Home", code: "Home", windowsVirtualKeyCode: 36, nativeVirtualKeyCode: 36, modifiers: 8
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Shift", code: "ShiftLeft", windowsVirtualKeyCode: 16, nativeVirtualKeyCode: 16
  });
}

async function pressCtrlK(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "k", code: "KeyK", windowsVirtualKeyCode: 75, nativeVirtualKeyCode: 75, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "k", code: "KeyK", windowsVirtualKeyCode: 75, nativeVirtualKeyCode: 75, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
}

async function pressCtrlHome(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Home", code: "Home", windowsVirtualKeyCode: 36, nativeVirtualKeyCode: 36, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Home", code: "Home", windowsVirtualKeyCode: 36, nativeVirtualKeyCode: 36, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
}

async function typeText(tabId, text) {
  // SmartEditor의 숨은 입력 프레임은 Input.insertText만으로는 반영되지 않는 경우가 있어
  // 실제 키 문자 이벤트를 사용한다. 저장·발행 계열 키는 절대 보내지 않는다.
  for (const char of String(text || "")) {
    await send(tabId, "Input.dispatchKeyEvent", {
      type: "char",
      text: char,
      unmodifiedText: char,
      key: char,
      windowsVirtualKeyCode: char.codePointAt(0) || 0,
      nativeVirtualKeyCode: char.codePointAt(0) || 0
    });
  }
}

async function pasteImage(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "v", code: "KeyV", windowsVirtualKeyCode: 86, nativeVirtualKeyCode: 86, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "v", code: "KeyV", windowsVirtualKeyCode: 86, nativeVirtualKeyCode: 86, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
}

const FIND_EDITOR_POINTS = `(() => {
  const visited = new Set();
  const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
    }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) {
      try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {}
    }
  };
  visit(document);
  const visible = (el) => {
    if (!el) return false;
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width > 30 && rect.height > 16;
  };
  const rootPoint = (el) => {
    const r = el.getBoundingClientRect();
    let x = r.left + Math.min(Math.max(r.width / 2, 20), Math.max(r.width - 20, 20));
    let y = r.top + Math.min(Math.max(r.height / 2, 20), Math.max(r.height - 20, 20));
    let w = el.ownerDocument.defaultView;
    while (w && w !== w.top) {
      const f = w.frameElement;
      if (!f) break;
      const fr = f.getBoundingClientRect(); x += fr.left; y += fr.top; w = w.parent;
    }
    return { x, y };
  };
  const first = (selectors, excluded) => {
    for (const root of docs) for (const selector of selectors) {
      for (const el of root.querySelectorAll(selector)) {
        if (el === excluded || !visible(el) || el.closest?.('[aria-hidden=true]')) continue;
        return el;
      }
    }
    return null;
  };
  const title = first(['.se-title-text', '.se-title [contenteditable=true]', 'input[placeholder*=제목]', '[contenteditable=true][aria-label*=제목]']);
  const body = first(['.se-content', '.se-component-content [contenteditable=true]', '.se-text-paragraph [contenteditable=true]', '[role=textbox][contenteditable=true]'], title);
  return { title: title ? rootPoint(title) : null, body: body ? rootPoint(body) : null };
})()`;

const FIND_LINK_DIALOG_INPUT = `(() => {
  const visited = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
    }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) {
      try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {}
    }
  };
  const point = (input) => {
    const rect = input.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2;
    let w = input.ownerDocument.defaultView;
    while (w && w !== w.top) { const f = w.frameElement; if (!f) break; const fr = f.getBoundingClientRect(); x += fr.left; y += fr.top; w = w.parent; }
    return { x, y };
  };
  visit(document);
  for (const root of docs) {
    const preferred = root.querySelector ? root.querySelector('.se-popup-oglink-input') : null;
    if (preferred) {
      const style = preferred.ownerDocument.defaultView.getComputedStyle(preferred); const rect = preferred.getBoundingClientRect();
      if (style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 20 && rect.height > 1) return point(preferred);
    }
  }
  for (const root of docs) for (const input of root.querySelectorAll ? root.querySelectorAll('input, textarea, [contenteditable=true], [role=textbox]') : []) {
    const style = input.ownerDocument.defaultView.getComputedStyle(input);
    const rect = input.getBoundingClientRect();
    const hint = ((input.placeholder || '') + ' ' + (input.getAttribute('aria-label') || '') + ' ' + (input.getAttribute('data-placeholder') || '') + ' ' + (input.name || '')).toLowerCase();
    if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 100 || rect.height < 16) continue;
    if (/url|링크|주소/.test(hint)) {
      return point(input);
    }
  }
  return null;
})()`;

function caretAfterTextExpression(text) {
  return `(() => {
    const original = ${JSON.stringify(text)};
    // 링크 적용 과정에서 SmartEditor가 제로폭 문자(카드 방지용)를 제거하거나 일반 URL 표기로 정규화할 수 있다.
    const candidates = [...new Set([
      original,
      original.replace(/\\u200B/g, ''),
      original.replace(/\\u200B/g, '').replace('://', ':\\u200B//')
    ].filter(Boolean))];
    const visited = new Set(); const docs = [];
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); docs.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
        try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
      }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) {
        try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {}
      }
    };
    visit(document);
    for (const doc of docs) {
      const walker = doc.createTreeWalker(doc.body || doc, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const value = node.nodeValue || '';
        const target = candidates.find((candidate) => value.includes(candidate));
        if (!target) continue;
        const index = value.indexOf(target);
        const range = doc.createRange();
        range.setStart(node, index + target.length); range.collapse(true);
        const selection = doc.defaultView?.getSelection?.();
        if (!selection) continue;
        selection.removeAllRanges(); selection.addRange(range);
        const editor = node.parentElement?.closest?.('[contenteditable=true]');
        try { editor?.focus?.(); } catch (_) {}
        return true;
      }
    }
    return false;
  })()`;
}

async function placeCaretAfterText(tabId, text) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const result = await send(tabId, "Runtime.evaluate", {
      expression: caretAfterTextExpression(text), returnByValue: true, awaitPromise: false
    });
    if (result?.result?.value) return true;
    await sleep(220);
  }
  return false;
}

const FIND_TOOLBAR_LINK_BUTTON = `(() => {
  const visited = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
    }
  };
  const point = (element) => {
    const rect = element.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2;
    let win = element.ownerDocument.defaultView;
    while (win && win !== win.top) { const frame = win.frameElement; if (!frame) break; const frameRect = frame.getBoundingClientRect(); x += frameRect.left; y += frameRect.top; win = win.parent; }
    return { x, y };
  };
  visit(document);
  for (const root of docs) for (const element of root.querySelectorAll ? root.querySelectorAll('button,[role=button],a') : []) {
    const hint = ((element.innerText || element.textContent || '') + ' ' + (element.getAttribute('aria-label') || '') + ' ' + (element.getAttribute('title') || '')).replace(/\\s+/g, ' ').trim();
    const style = element.ownerDocument.defaultView.getComputedStyle(element); const rect = element.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 14 || rect.height < 14) continue;
    if (hint === '링크' || (/링크/.test(hint) && element.closest('[class*=toolbar], [class*=ToolBar], [class*=se-toolbar]'))) return point(element);
  }
  return null;
})()`;

const FIND_LINK_DIALOG_CONFIRM = `(() => {
  const visited = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
    }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) {
      try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {}
    }
  };
  const point = (element) => {
    const rect = element.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2;
    let win = element.ownerDocument.defaultView;
    while (win && win !== win.top) { const frame = win.frameElement; if (!frame) break; const frameRect = frame.getBoundingClientRect(); x += frameRect.left; y += frameRect.top; win = win.parent; }
    return { x, y };
  };
  visit(document);
  for (const root of docs) for (const element of root.querySelectorAll ? root.querySelectorAll('button,[role=button]') : []) {
    const label = (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').trim();
    const style = element.ownerDocument.defaultView.getComputedStyle(element); const rect = element.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 20 || rect.height < 16) continue;
    if (/^(확인|적용|등록|완료)$/.test(label) && !element.disabled && element.getAttribute('aria-disabled') !== 'true') return point(element);
  }
  return null;
})()`;

function activateLinkDialogInputExpression(url) {
  return `(() => {
    const target = ${JSON.stringify(url)};
    const visited = new Set(); const docs = [];
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); docs.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    for (const root of docs) {
      const input = root.querySelector ? root.querySelector('.se-popup-oglink-input') : null;
      if (!input) continue;
      const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      try { descriptor?.set?.call(input, target); } catch (_) { input.value = target; }
      try { input.focus(); } catch (_) {}
      input.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: target, inputType: 'insertText' }));
      input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      input.dispatchEvent(new FocusEvent('blur', { bubbles: true, composed: true }));
      return true;
    }
    return false;
  })()`;
}

const IS_LINK_DIALOG_OPEN = `(() => {
  const visited = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
  };
  visit(document);
  return docs.some((root) => {
    const input = root.querySelector ? root.querySelector('.se-popup-oglink-input') : null;
    if (!input) return false;
    const style = input.ownerDocument.defaultView.getComputedStyle(input); const rect = input.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 20 && rect.height > 1;
  });
})()`;

async function waitForLinkDialogClosed(tabId, attempts = 14) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', { expression: IS_LINK_DIALOG_OPEN, returnByValue: true, awaitPromise: false });
    if (!result?.result?.value) return true;
    await sleep(250);
  }
  return false;
}

function displayTextWithoutUrlRecognition(url) {
  // 화면에는 URL과 똑같이 보이지만, 일반 본문 입력 단계에서 자동 링크 카드가 생성되는 것을 막는다.
  return String(url).replace('://', ':\u200B//');
}

const LINK_SELECTION_TRACE = `(() => {
  const visitedRoots = new Set(); const visitedDocs = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visitedRoots.has(root)) return;
    visitedRoots.add(root);
    const doc = root?.nodeType === 9 ? root : root.ownerDocument;
    if (doc && !visitedDocs.has(doc)) { visitedDocs.add(doc); docs.push(doc); }
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
  };
  const elementInfo = (element) => {
    if (!element) return null;
    const rect = element.getBoundingClientRect?.() || { left: 0, top: 0, width: 0, height: 0 };
    return {
      tag: element.tagName || '', className: String(element.className || '').slice(0, 160),
      ariaLabel: String(element.getAttribute?.('aria-label') || '').slice(0, 80), title: String(element.getAttribute?.('title') || '').slice(0, 80),
      rect: { left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }
    };
  };
  visit(document);
  const selectionDocuments = docs.map((doc, index) => {
    const selection = doc.getSelection?.(); const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    const active = doc.activeElement;
    return {
      documentIndex: index, nodeType: doc.nodeType, bodyContentEditable: Boolean(doc.body?.isContentEditable),
      activeElement: elementInfo(active), rangeCount: selection?.rangeCount || 0, isCollapsed: selection ? Boolean(selection.isCollapsed) : null,
      selectedLength: selection ? selection.toString().length : 0,
      anchorNodeType: selection?.anchorNode?.nodeType || 0, focusNodeType: selection?.focusNode?.nodeType || 0,
      rangeCommonAncestorTag: range?.commonAncestorContainer?.parentElement?.tagName || ''
    };
  });
  const linkButtons = [];
  for (const doc of docs) for (const element of doc.querySelectorAll?.('button,[role=button],a') || []) {
    const label = ((element.getAttribute('aria-label') || '') + ' ' + (element.getAttribute('title') || '') + ' ' + (element.innerText || element.textContent || '')).replace(/\\s+/g, ' ').trim();
    if (!/링크|link/i.test(label)) continue;
    const style = doc.defaultView?.getComputedStyle(element); const rect = element.getBoundingClientRect();
    if (style?.display === 'none' || style?.visibility === 'hidden' || rect.width < 10 || rect.height < 10) continue;
    linkButtons.push({ ...elementInfo(element), disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true') });
  }
  return { selectionDocuments, linkButtons: linkButtons.slice(0, 20) };
})()`;

async function recordLinkTrace(tabId, stage) {
  const result = await send(tabId, 'Runtime.evaluate', { expression: LINK_SELECTION_TRACE, returnByValue: true, awaitPromise: false });
  const trace = { stage, capturedAt: Date.now(), ...(result?.result?.value || {}) };
  const stored = await chrome.storage.session.get(LINK_TRACE_KEY);
  const previous = stored[LINK_TRACE_KEY];
  const stages = { ...(previous?.stages || {}), [stage]: trace };
  const merged = { latestStage: stage, stages };
  await chrome.storage.session.set({ [LINK_TRACE_KEY]: merged });
  return trace;
}

function selectRenderedTextExpression(text) {
  return `(() => {
    const target = ${JSON.stringify(text)};
    const visitedRoots = new Set(); const visitedDocs = new Set(); const docs = [];
    const visit = (root) => {
      if (!root || visitedRoots.has(root)) return;
      visitedRoots.add(root);
      const doc = root?.nodeType === 9 ? root : root.ownerDocument;
      if (doc && !visitedDocs.has(doc)) { visitedDocs.add(doc); docs.push(doc); }
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    for (let documentIndex = 0; documentIndex < docs.length; documentIndex += 1) {
      const doc = docs[documentIndex];
      const walker = doc.createTreeWalker(doc.body || doc, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const value = node.nodeValue || ''; const start = value.indexOf(target);
        if (start < 0) continue;
        const range = doc.createRange(); range.setStart(node, start); range.setEnd(node, start + target.length);
        const selection = doc.defaultView?.getSelection?.(); if (!selection) continue;
        selection.removeAllRanges(); selection.addRange(range);
        const selectedLength = selection.toString().length;
        if (selectedLength === target.length) return { selected: true, documentIndex, selectedLength };
      }
    }
    return { selected: false, documentIndex: -1, selectedLength: 0 };
  })()`;
}

const FIND_PROPERTY_LINK_BUTTON = `(() => {
  const visited = new Set(); const docs = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); docs.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
  };
  const point = (element) => {
    const rect = element.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2;
    let win = element.ownerDocument.defaultView;
    while (win && win !== win.top) { const frame = win.frameElement; if (!frame) break; const frameRect = frame.getBoundingClientRect(); x += frameRect.left; y += frameRect.top; win = win.parent; }
    return { x, y, className: String(element.className || '').slice(0, 180) };
  };
  visit(document);
  for (const root of docs) for (const element of root.querySelectorAll ? root.querySelectorAll('.se-link-toolbar-button') : []) {
    const style = element.ownerDocument.defaultView.getComputedStyle(element); const rect = element.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 10 || rect.height < 10) continue;
    if (!element.disabled && element.getAttribute('aria-disabled') !== 'true') return point(element);
  }
  return null;
})()`;

function fillPropertyLinkLayerExpression(url) {
  return `(() => {
    const target = ${JSON.stringify(url)};
    const visited = new Set(); const roots = [];
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); roots.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    for (const root of roots) {
      const input = root.querySelector?.('.se-custom-layer-link-input');
      if (!input) continue;
      const view = input.ownerDocument?.defaultView;
      const descriptor = Object.getOwnPropertyDescriptor(view?.HTMLInputElement?.prototype || HTMLInputElement.prototype, 'value');
      try { descriptor?.set?.call(input, target); } catch (_) { input.value = target; }
      input.focus();
      input.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: target, inputType: 'insertText' }));
      input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, composed: true, key: 'l', code: 'KeyL' }));
      return true;
    }
    return false;
  })()`;
}

const FIND_PROPERTY_LINK_APPLY = `(() => {
  const visited = new Set(); const roots = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); roots.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
  };
  const point = (element) => {
    const rect = element.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2;
    let win = element.ownerDocument.defaultView;
    while (win && win !== win.top) { const frame = win.frameElement; if (!frame) break; const frameRect = frame.getBoundingClientRect(); x += frameRect.left; y += frameRect.top; win = win.parent; }
    return { x, y };
  };
  visit(document);
  for (const root of roots) {
    const button = root.querySelector?.('.se-custom-layer-link-apply-button');
    if (!button) continue;
    const style = button.ownerDocument.defaultView.getComputedStyle(button); const rect = button.getBoundingClientRect();
    if (style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 10 && rect.height >= 10 && !button.disabled && button.getAttribute('aria-disabled') !== 'true') return point(button);
  }
  return null;
})()`;

const IS_PROPERTY_LINK_LAYER_OPEN = `(() => {
  const visited = new Set(); const roots = [];
  const visit = (root) => {
    if (!root || visited.has(root)) return;
    visited.add(root); roots.push(root);
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
    for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
  };
  visit(document);
  return roots.some((root) => {
    const input = root.querySelector?.('.se-custom-layer-link-input');
    if (!input) return false;
    const style = input.ownerDocument.defaultView.getComputedStyle(input); const rect = input.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 10 && rect.height >= 10;
  });
})()`;

function hasRenderedHrefExpression(url) {
  return `(() => {
    const target = ${JSON.stringify(url)}; const visited = new Set(); const roots = [];
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); roots.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    return roots.some((root) => [...(root.querySelectorAll?.('a[href]') || [])].some((link) => link.href === target || link.getAttribute('href') === target));
  })()`;
}

async function waitForPropertyLinkLayerClosed(tabId, attempts = 16) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', { expression: IS_PROPERTY_LINK_LAYER_OPEN, returnByValue: true, awaitPromise: false });
    if (!result?.result?.value) return true;
    await sleep(180);
  }
  return false;
}

function applyInlineLinkExpression(url) {
  return `(() => {
    const target = ${JSON.stringify(url)};
    const visitedRoots = new Set(); const visitedDocs = new Set(); const docs = [];
    const visit = (root) => {
      if (!root || visitedRoots.has(root)) return;
      visitedRoots.add(root);
      // iframe 문서는 다른 전역 객체에 속해 instanceof Document가 실패할 수 있으므로 nodeType으로 판별한다.
      const doc = root?.nodeType === 9 ? root : root.ownerDocument;
      if (doc && !visitedDocs.has(doc)) { visitedDocs.add(doc); docs.push(doc); }
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    for (const doc of docs) {
      const selection = doc.getSelection?.();
      if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) continue;
      const applied = doc.execCommand?.('createLink', false, target);
      if (!applied) continue;
      const links = [...doc.querySelectorAll('a[href]')];
      if (links.some((link) => link.href === target || link.getAttribute('href') === target)) return true;
    }
    return false;
  })()`;
}

async function waitForPoint(tabId, expression, attempts = 12) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, "Runtime.evaluate", { expression, returnByValue: true, awaitPromise: false });
    const point = result?.result?.value;
    if (point?.x && point?.y) return point;
    await sleep(220);
  }
  return null;
}

async function insertCardlessLink(tabId, url) {
  if (!url) throw new Error("상품 링크가 비어 있습니다.");
  // 이 SmartEditor는 선택한 URL 표시 텍스트를 링크로 바꾸는 대신 실제 URL을 뒤에 추가한다.
  // 따라서 화면에 보이지 않는 문자 하나만 선택하고 속성 링크 도구에 URL을 넣어, 실제 일반 링크 한 개만 생성한다.
  const linkSeed = "\u2060";
  await typeText(tabId, linkSeed);
  // 숨은 input_buffer에 보내는 Shift+Home은 화면 본문의 DOM 선택 범위를 만들지 못한다.
  // 렌더링된 비가시 자리표시자를 직접 범위 선택한 뒤, 외부 링크 카드 도구가 아닌 속성 링크 버튼만 누른다.
  const selectionResult = await send(tabId, 'Runtime.evaluate', { expression: selectRenderedTextExpression(linkSeed), returnByValue: true, awaitPromise: false });
  const selected = selectionResult?.result?.value;
  await recordLinkTrace(tabId, 'after-rendered-dom-selection');
  if (!selected?.selected) throw new Error('렌더링된 URL 표시 텍스트의 선택 범위를 만들지 못했습니다. 비민감 진단을 복사해 주세요.');
  const propertyLinkPoint = await waitForPoint(tabId, FIND_PROPERTY_LINK_BUTTON, 8);
  if (!propertyLinkPoint) throw new Error('선택 텍스트용 링크 버튼을 찾지 못했습니다. 비민감 진단을 복사해 주세요.');
  await click(tabId, propertyLinkPoint);
  await sleep(250);
  await recordLinkTrace(tabId, 'after-property-link-button');
  const layerFilled = await send(tabId, 'Runtime.evaluate', { expression: fillPropertyLinkLayerExpression(url), returnByValue: true, awaitPromise: false });
  if (!layerFilled?.result?.value) throw new Error('선택 텍스트용 링크 입력칸을 찾지 못했습니다. 비민감 진단을 복사해 주세요.');
  const applyPoint = await waitForPoint(tabId, FIND_PROPERTY_LINK_APPLY, 10);
  if (!applyPoint) throw new Error('선택 텍스트용 링크 적용 버튼이 활성화되지 않았습니다. 비민감 진단을 복사해 주세요.');
  await click(tabId, applyPoint);
  if (!await waitForPropertyLinkLayerClosed(tabId)) throw new Error('선택 텍스트용 링크 레이어가 닫히지 않았습니다. 비민감 진단을 복사해 주세요.');
  const hrefResult = await send(tabId, 'Runtime.evaluate', { expression: hasRenderedHrefExpression(url), returnByValue: true, awaitPromise: false });
  await recordLinkTrace(tabId, 'after-property-link-apply');
  // SmartEditor may commit the property link to its internal document model before a DOM anchor is exposed.
  // A closed link layer confirms the apply action; do not stop later body and image input on a transient DOM miss.
  const stored = await chrome.storage.session.get(LINK_TRACE_KEY);
  await chrome.storage.session.set({ [LINK_TRACE_KEY]: { ...(stored[LINK_TRACE_KEY] || {}), renderedHrefVerified: Boolean(hrefResult?.result?.value) } });

  const trace = await chrome.storage.session.get(LINK_TRACE_KEY);
  await chrome.storage.session.set({ [LINK_TRACE_KEY]: { ...(trace[LINK_TRACE_KEY] || {}), invisibleLinkSeedUsed: true } });
  return { invisibleLinkSeedUsed: true };
}

const FIND_TOSS_LINK_PREVIEW = (shareUrl) => `(() => {
  const expected = ${JSON.stringify(shareUrl)};
  const visited = new Set();
  const visit = (root, offsetX = 0, offsetY = 0) => {
    if (!root || visited.has(root)) return null;
    visited.add(root);
    for (const link of root.querySelectorAll ? root.querySelectorAll('a[href]') : []) {
      const href = link.href || link.getAttribute('href') || '';
      if (!href || (expected && !href.includes(expected) && !expected.includes(href))) continue;
      let node = link.parentElement;
      for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        const hasImage = node.querySelector && node.querySelector('img');
        if (hasImage && rect.width >= 100 && rect.height >= 80) {
          return { x: offsetX + rect.left + rect.width / 2, y: offsetY + rect.top + Math.min(rect.height / 2, 40) };
        }
      }
    }
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try {
        const rect = frame.getBoundingClientRect();
        const found = visit(frame.contentDocument, offsetX + rect.left, offsetY + rect.top);
        if (found) return found;
      } catch (_) {}
    }
    return null;
  };
  return visit(document);
})()`;

async function dismissTossLinkPreview(tabId, shareUrl) {
  if (!shareUrl) return false;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const result = await send(tabId, "Runtime.evaluate", {
      expression: FIND_TOSS_LINK_PREVIEW(shareUrl), returnByValue: true, awaitPromise: false
    });
    const point = result?.result?.value;
    if (point?.x && point?.y) {
      await click(tabId, point);
      await sleep(180);
      await pressDelete(tabId);
      await sleep(350);
      return true;
    }
    await sleep(300);
  }
  return false;
}

const FIND_EXISTING_DRAFT_CANCEL = `(() => {
  const visited = new Set();
  const visit = (root, offsetX = 0, offsetY = 0) => {
    if (!root || visited.has(root)) return null;
    visited.add(root);
    const pageText = root.body?.innerText || root.textContent || '';
    if (pageText.includes('작성 중인 글이 있습니다')) {
      for (const button of root.querySelectorAll('button')) {
        if ((button.innerText || button.textContent || '').trim() !== '취소') continue;
        const rect = button.getBoundingClientRect();
        const style = button.ownerDocument.defaultView.getComputedStyle(button);
        if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 20 || rect.height < 16) continue;
        return { x: offsetX + rect.left + rect.width / 2, y: offsetY + rect.top + rect.height / 2 };
      }
    }
    for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
      try {
        const rect = frame.getBoundingClientRect();
        const found = visit(frame.contentDocument, offsetX + rect.left, offsetY + rect.top);
        if (found) return found;
      } catch (_) {}
    }
    return null;
  };
  return visit(document);
})()`;

async function dismissExistingDraftDialog(tabId) {
  // 사용자가 명시적으로 승인한 '작성 중인 글이 있습니다' 창의 취소 버튼만 클릭한다.
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const result = await send(tabId, "Runtime.evaluate", { expression: FIND_EXISTING_DRAFT_CANCEL, returnByValue: true, awaitPromise: false });
    const point = result?.result?.value;
    if (point?.x && point?.y) {
      await click(tabId, point);
      await sleep(650);
      return true;
    }
    await sleep(250);
  }
  return false;
}

async function findEditorPoints(tabId) {
  for (let attempt = 0; attempt < 24; attempt += 1) {
    const result = await send(tabId, "Runtime.evaluate", { expression: FIND_EDITOR_POINTS, returnByValue: true, awaitPromise: false });
    const points = result?.result?.value;
    if (points?.title && points?.body) return points;
    await sleep(500);
  }
  throw new Error("네이버 제목 또는 본문 영역을 자동으로 찾지 못했습니다.");
}

async function insertBody(tabId, body, tags = "") {
  const blocks = `${body}${tags ? `\n\n${tags}` : ""}`
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  for (let blockIndex = 0; blockIndex < blocks.length; blockIndex += 1) {
    const lines = blocks[blockIndex].split("\n").map((line) => line.trim()).filter(Boolean);
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      await typeText(tabId, lines[lineIndex]);
      if (lineIndex < lines.length - 1) await pressEnter(tabId);
    }
    if (blockIndex < blocks.length - 1) {
      // 실제 빈 문단 하나를 넣어 주요 구역 간 가독성을 확보한다.
      await pressEnter(tabId);
      await pressEnter(tabId);
    }
  }
}

function buildReadableBodyLayout(draft) {
  const sections = String(draft.body || "")
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    // 서버 초안의 이미지 자리표시자는 실제 이미지를 클립보드로 붙이므로 본문 텍스트로 입력하지 않는다.
    .filter((item) => Boolean(item) && item !== "[이미지 영역]");
  const linkIndex = sections.findIndex((section) => /https?:\/\/\S+/i.test(section));
  const linkSection = linkIndex >= 0 ? sections[linkIndex] : "";
  const linkLines = linkSection.split("\n").map((line) => line.trim()).filter(Boolean);
  const shareUrl = linkLines.find((line) => /https?:\/\/\S+/i.test(line)) || "";
  const linkLabel = linkLines.filter((line) => line !== shareUrl).join("\n");
  const beforeImage = linkIndex >= 0 ? [...sections.slice(0, linkIndex), linkLabel].filter(Boolean) : [];
  const notices = linkIndex >= 0 ? sections.slice(linkIndex + 1) : sections;
  const normalizedTitle = String(draft.title || "").replace(/\s+/g, " ").trim();
  // 일부 네이버 입력 경로가 제목을 본문에도 복제하는 경우에도 이미지 아래 중복 요약을 제거한다.
  const visibleNotices = notices.filter((section) => section.replace(/\s+/g, " ").trim() !== normalizedTitle);
  const disclosure = visibleNotices.filter((section) => /수수료를 제공받습니다/.test(section));
  const recommendation = visibleNotices.filter((section) => !/수수료를 제공받습니다/.test(section));
  // 링크 카드가 상품명·가격을 별도로 보여 주므로 수동 제목을 다시 넣지 않아 중복을 방지한다.
  const afterImage = [...recommendation, draft.tags, ...disclosure].filter(Boolean);
  return {
    beforeImage: beforeImage.join("\n\n"),
    shareUrl,
    afterImage: afterImage.join("\n\n")
  };
}

function verificationExpression(title, bodyMarker) {
  return `(() => {
    const visited = new Set(); const docs = [];
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); docs.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) {
        try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {}
      }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) {
        try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {}
      }
    };
    visit(document);
    const text = docs.map((root) => root.body?.innerText || root.textContent || '').join('\\n');
    const images = docs.reduce((count, root) => count + root.querySelectorAll('img').length, 0);
    return { titlePresent: text.includes(${JSON.stringify(title)}), bodyPresent: text.includes(${JSON.stringify(bodyMarker)}), imageCount: images, documentCount: docs.length };
  })()`;
}

async function waitForPastedImage(tabId, baselineImages, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await send(tabId, "Runtime.evaluate", {
      expression: verificationExpression("", ""),
      returnByValue: true,
      awaitPromise: false
    });
    const imageCount = Number(result?.result?.value?.imageCount || 0);
    if (imageCount > Number(baselineImages || 0)) return true;
    await sleep(350);
  }
  return false;
}

async function verifyApplied(tabId, draft, baselineImages) {
  await sleep(1100);
  const result = await send(tabId, "Runtime.evaluate", {
    expression: verificationExpression(draft.title, draft.body.slice(0, Math.min(20, draft.body.length))),
    returnByValue: true,
    awaitPromise: false
  });
  const report = result?.result?.value || {};
  report.imageInserted = Number(report.imageCount || 0) > Number(baselineImages || 0);
  return report;
}

async function autoFillNaver(tabId, draft) {
  await recordAutoFillTrace({ stage: "starting", completed: false, failed: false });
  await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
  try {
    await dismissExistingDraftDialog(tabId);
    const points = await findEditorPoints(tabId);
    await recordAutoFillTrace({ stage: "editor-points-found" });
    const before = await send(tabId, "Runtime.evaluate", { expression: verificationExpression("", ""), returnByValue: true, awaitPromise: false });
    const baselineImages = before?.result?.value?.imageCount || 0;
    await click(tabId, points.title);
    await sleep(240);
    await typeText(tabId, draft.title);
    await sleep(260);
    await click(tabId, points.body);
    await sleep(240);
    const layout = buildReadableBodyLayout(draft);
    // SmartEditor는 Ctrl+V 이미지 처리를 늦게 완료할 수 있다. 이미지를 먼저 붙이고 텍스트를 이어 쓰면
    // 처리 시점의 커서가 마지막 문단으로 이동해 이미지도 글 맨 아래에 놓인다.
    // 따라서 텍스트를 먼저 입력하고, 본문 시작점으로 이동한 뒤 이미지를 마지막 입력 명령으로 붙인다.
    if (layout.beforeImage) await insertBody(tabId, layout.beforeImage);
    if (!layout.shareUrl) throw new Error("상품 링크를 찾지 못했습니다. 이미지 입력을 중단했습니다.");
    await pressEnter(tabId);
    const linkResult = await insertCardlessLink(tabId, layout.shareUrl);
    await recordAutoFillTrace({ stage: "property-link-applied", invisibleLinkSeedUsed: linkResult.invisibleLinkSeedUsed });

    // 이미지 붙여넣기를 후속 본문보다 먼저 완료한다. 그래야 네이버의 늦은 Ctrl+V 처리도 링크 바로 아래 위치를 사용한다.
    await pressEnter(tabId);
    await pasteImage(tabId);
    const imagePasted = await waitForPastedImage(tabId, baselineImages);
    if (!imagePasted) throw new Error("원본 대표 이미지 붙여넣기를 확인하지 못했습니다. 이미지 없는 글 입력을 중단했습니다.");
    await recordAutoFillTrace({ stage: "image-pasted-below-link", invisibleLinkSeedUsed: linkResult.invisibleLinkSeedUsed });

    if (layout.afterImage) {
      await pressEnter(tabId);
      await pressEnter(tabId);
      await insertBody(tabId, layout.afterImage);
    }
    await recordAutoFillTrace({ stage: "after-image-text-inserted", invisibleLinkSeedUsed: linkResult.invisibleLinkSeedUsed });
    await sleep(450);
    const report = await verifyApplied(tabId, draft, baselineImages);
    // SmartEditor는 본문과 클립보드 이미지를 별도 내부 렌더링으로 보관할 수 있어,
    // 일반 DOM 텍스트·img 탐색이 false여도 실제 화면에는 정상 반영될 수 있다.
    // 제목 반영은 확실히 확인하고, 본문·이미지는 입력 명령 완료 후 사용자가 화면에서 확인한다.
    if (!report.titlePresent) {
      throw new Error(`자동 입력이 화면에 반영되지 않았습니다. 제목=false, 탐지문서=${Number(report.documentCount || 0)}`);
    }
    report.bodyVerificationLimited = !report.bodyPresent;
    report.imageVerificationLimited = !report.imageInserted;
    await recordAutoFillTrace({
      stage: "completed",
      completed: true,
      failed: false,
      titlePresent: Boolean(report.titlePresent),
      bodyPresent: Boolean(report.bodyPresent),
      imageInserted: Boolean(report.imageInserted),
      bodyVerificationLimited: Boolean(report.bodyVerificationLimited),
      imageVerificationLimited: Boolean(report.imageVerificationLimited),
      documentCount: Number(report.documentCount || 0)
    });
    return report;
  } catch (error) {
    await recordAutoFillTrace({
      stage: "failed",
      completed: false,
      failed: true,
      error: String(error?.message || "auto-fill-error").slice(0, 240)
    });
    throw error;
  } finally {
    await chrome.debugger.detach({ tabId }).catch(() => undefined);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type === "BLOGAUTO_STORE_DRAFT") {
      if (!isBlogAutoSender(sender)) throw new Error("허용되지 않은 초안 요청입니다.");
      const draft = normalizeDraft(message.draft);
      await chrome.storage.session.set({ [DRAFT_KEY]: draft });
      sendResponse({ ok: true, expiresAt: draft.expiresAt });
      return;
    }

    if (message?.type === "NAVER_GET_LINK_TRACE") {
      if (!isNaverEditorSender(sender)) throw new Error("네이버 글쓰기 화면에서만 사용할 수 있습니다.");
      const stored = await chrome.storage.session.get(LINK_TRACE_KEY);
      sendResponse({ ok: true, trace: stored[LINK_TRACE_KEY] || null });
      return;
    }

    if (message?.type === "NAVER_GET_AUTOFILL_TRACE") {
      if (!isNaverEditorSender(sender)) throw new Error("?ㅼ씠踰?湲?곌린 ?붾㈃?먯꽌留??ъ슜?????덉뒿?덈떎.");
      const stored = await chrome.storage.session.get(AUTOFILL_TRACE_KEY);
      sendResponse({ ok: true, trace: stored[AUTOFILL_TRACE_KEY] || null });
      return;
    }

    if (message?.type === "NAVER_GET_DRAFT") {
      if (!isNaverEditorSender(sender)) throw new Error("네이버 글쓰기 화면에서만 사용할 수 있습니다.");
      sendResponse({ ok: true, draft: await getLiveDraft() });
      return;
    }

    if (message?.type === "NAVER_AUTO_FILL") {
      if (!isNaverEditorSender(sender) || !sender.tab?.id) throw new Error("네이버 글쓰기 화면에서만 자동 입력할 수 있습니다.");
      const draft = await getLiveDraft();
      if (!draft || draft.id !== message.draftId) throw new Error("준비된 초안을 찾지 못했습니다.");
      const report = await autoFillNaver(sender.tab.id, draft);
      await chrome.storage.session.remove(DRAFT_KEY);
      sendResponse({ ok: true, report });
      return;
    }

    if (message?.type === "NAVER_CONSUME_DRAFT") {
      if (!isNaverEditorSender(sender)) throw new Error("허용되지 않은 초안 처리 요청입니다.");
      const draft = await getLiveDraft();
      if (draft?.id === message.draftId) await chrome.storage.session.remove(DRAFT_KEY);
      sendResponse({ ok: true });
      return;
    }

    throw new Error("지원하지 않는 요청입니다.");
  })().catch((error) => sendResponse({ ok: false, error: error.message || "확장 프로그램 오류" }));
  return true;
});
