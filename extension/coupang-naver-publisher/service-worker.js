const DRAFT_KEY = "pendingCoupangNaverDraft";
const DRAFT_TTL_MS = 10 * 60 * 1000;
const BLOGAUTO_ORIGIN = "https://blogauto.hongzi.us";
const DEBUGGER_VERSION = "1.3";
const LINK_TRACE_KEY = "coupangNaverPublisherLinkTrace";
const AUTOFILL_TRACE_KEY = "coupangNaverPublisherAutoFillTrace";
const DEVICE_TOKEN_KEY = "coupangNaverPublisherDeviceToken";
const PAIR_TAB_ID_KEY = "coupangNaverPublisherPairTabId";
const APPROVAL_ALARM = "coupangNaverPublisherApprovalPoll";
const clipboardPrepPorts = new Map();
let imageClipboardPort = null;
let creatingImageClipboardDocument = null;
let approvalDispatchInFlight = false;
chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
// 서비스 워커가 어떤 확장 이벤트로 다시 깨어나도 다음 승인 폴링 알람을 보장한다.
chrome.alarms.create(APPROVAL_ALARM, { periodInMinutes: 1 });

chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "naver-draft-image-offscreen") {
    imageClipboardPort = port;
    port.onDisconnect.addListener(() => {
      if (imageClipboardPort === port) imageClipboardPort = null;
    });
    return;
  }
  if (port.name !== "naver-draft-clipboard-prep" || !port.sender?.tab?.id) return;
  const tabId = port.sender.tab.id;
  clipboardPrepPorts.set(tabId, port);
  port.onDisconnect.addListener(() => clipboardPrepPorts.delete(tabId));
});

async function waitForClipboardPrepPort(tabId) {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const port = clipboardPrepPorts.get(tabId);
    if (port) return port;
    await sleep(100);
  }
  throw new Error("이미지 준비 탭 연결 시간이 초과되었습니다.");
}

async function hasImageClipboardDocument() {
  const documentUrl = chrome.runtime.getURL("offscreen.html");
  if (typeof chrome.runtime.getContexts === "function") {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"],
      documentUrls: [documentUrl],
    });
    return contexts.length > 0;
  }
  const clientsList = await clients.matchAll();
  return clientsList.some((client) => client.url === documentUrl);
}

async function ensureImageClipboardDocument() {
  // Chrome의 권장 방식대로 문서 존재 여부만 확인한다.
  // 메시지는 runtime.sendMessage로 전달하므로 서비스 워커 재시작 뒤의 장기 포트 상태에 의존하지 않는다.
  if (await hasImageClipboardDocument()) return;
  if (!creatingImageClipboardDocument) {
    creatingImageClipboardDocument = chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["CLIPBOARD"],
      justification: "원본 상품 이미지를 PNG 클립보드 데이터로 준비해 네이버 편집기에 붙여넣습니다.",
    });
  }
  try {
    await creatingImageClipboardDocument;
  } finally {
    creatingImageClipboardDocument = null;
  }
}

async function closeImageClipboardDocument() {
  if (creatingImageClipboardDocument) await creatingImageClipboardDocument.catch(() => undefined);
  if (await hasImageClipboardDocument().catch(() => false)) {
    await chrome.offscreen.closeDocument().catch(() => undefined);
  }
}

async function waitForImageClipboardPort() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (imageClipboardPort) return imageClipboardPort;
    await sleep(100);
  }
  throw new Error("숨겨진 이미지 준비 문서에 연결하지 못했습니다.");
}

async function prepareApprovedImage(imageUrl, windowId) {
  // 포커스를 가진 일반 Chrome 전용 탭에서만 PNG 클립보드를 준비한다.
  // 숨은 문서는 Chrome이 클립보드 쓰기를 차단하므로 사용하지 않는다.
  const safeUrl = safeImageUrl(imageUrl);
  if (!safeUrl) throw new Error("원본 대표 이미지 주소를 확인하지 못했습니다.");
  const createProperties = { url: chrome.runtime.getURL("clipboard-prep.html"), active: true };
  if (Number.isInteger(windowId)) createProperties.windowId = windowId;
  const prepTab = await chrome.tabs.create(createProperties);
  if (!Number.isInteger(prepTab?.id)) throw new Error("원본 이미지 준비용 전용 탭을 열지 못했습니다.");
  try {
    const port = await waitForClipboardPrepPort(prepTab.id);
    const requestId = crypto.randomUUID();
    await new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        port.onMessage.removeListener(onMessage);
        if (error) reject(error); else resolve();
      };
      const onMessage = (message) => {
        if (message?.requestId !== requestId) return;
        if (message?.ok) finish();
        else finish(new Error(String(message?.error || "원본 대표 이미지 클립보드 준비에 실패했습니다.")));
      };
      const timeoutId = setTimeout(() => finish(new Error("원본 이미지 준비 탭의 버튼을 60초 안에 누르지 않았습니다.")), 60000);
      port.onMessage.addListener(onMessage);
      try {
        port.postMessage({ type: "CLIPBOARD_PREPARE_IMAGE", requestId, imageUrl: safeUrl, autoAttempt: true });
        // Chrome의 실제 입력 경로를 사용해 준비 탭의 버튼을 한 번 자동 클릭한다.
        // 브라우저 정책이 이를 사용자 활성화로 인정하지 않으면 준비 탭은 수동 1회 복구 상태로 남는다.
        autoClickClipboardPrepButton(prepTab.id).catch((error) => {
          recordApprovalDispatchTrace({ step: "clipboard_auto_click_unavailable", error: String(error?.message || "auto-click-unavailable").slice(0, 240) }).catch(() => undefined);
        });
      } catch (error) {
        finish(error);
      }
    });
    return prepTab.id;
  } catch (error) {
    await chrome.tabs.remove(prepTab.id).catch(() => undefined);
    throw error;
  }
}

async function recordApprovalDispatchTrace(patch) {
  const stored = await chrome.storage.local.get("coupangNaverPublisherApprovalTrace");
  await chrome.storage.local.set({
    coupangNaverPublisherApprovalTrace: { ...(stored.coupangNaverPublisherApprovalTrace || {}), ...patch, updatedAt: Date.now() },
  });
}

async function pollApprovedDraft() {
  if (approvalDispatchInFlight) return;
  approvalDispatchInFlight = true;
  try {
    const { [DEVICE_TOKEN_KEY]: deviceToken, [PAIR_TAB_ID_KEY]: pairTabId } = await chrome.storage.local.get([DEVICE_TOKEN_KEY, PAIR_TAB_ID_KEY]);
  if (!deviceToken) return;
  await recordApprovalDispatchTrace({ step: "polling", error: "" });
  const response = await fetch(`${BLOGAUTO_ORIGIN}/api/coupang/extension/approved-draft`, {
    headers: { "X-Naver-Draft-Device": deviceToken },
    cache: "no-store",
  });
  if (response.status === 401) {
    await chrome.storage.local.remove(DEVICE_TOKEN_KEY);
    return;
  }
  if (!response.ok) return;
  const payload = await response.json().catch(() => ({}));
  if (!payload?.ok || !payload.result?.draft) return;
    let clipboardPrepTabId = null;
    let naverAutomationTabId = null;
    let naverAutomationWindowId;
    let claimAcquired = false;
    try {
      const batchId = String(payload.result.batch_id || '');
      const claimResponse = await fetch(`${BLOGAUTO_ORIGIN}/api/coupang/extension/approved-draft/claim`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Naver-Draft-Device': deviceToken },
        body: JSON.stringify({ batch_id: batchId }),
      });
      const claimPayload = await claimResponse.json().catch(() => ({}));
      if (!claimResponse.ok || claimPayload?.result?.claimed !== true) throw new Error('다른 쿠팡 전용 확장이 이미 이 승인 배치를 가져갔습니다.');
      claimAcquired = true;
      const draft = normalizeDraft({ ...(payload.result.draft || {}), product: payload.result.product || null });

    // 별도 팝업은 사용하지 않는다. 페어링한 blogauto 탭과 같은 일반 Chrome 창에
    // 전용 자동화 탭만 열고, 완료·실패 후 자동화가 만든 탭들만 닫는다.
    // 기존 사용자 탭은 탐색·닫기 대상이 아니다.
    const pairedTab = Number.isInteger(pairTabId)
      ? await chrome.tabs.get(pairTabId).catch(() => null)
      : null;
    const automationWindowId = Number.isInteger(pairedTab?.windowId) ? pairedTab.windowId : undefined;
    clipboardPrepTabId = await prepareApprovedImage(draft.imageUrl, automationWindowId);
    draft.clipboardPrepTabId = clipboardPrepTabId;
    const createProperties = { url: "about:blank", active: true };
    if (Number.isInteger(automationWindowId)) createProperties.windowId = automationWindowId;
    const automationTab = await chrome.tabs.create(createProperties);
    if (!Number.isInteger(automationTab?.id)) throw new Error("자동 발행용 네이버 전용 탭을 열지 못했습니다.");
    naverAutomationTabId = automationTab.id;
    draft.naverAutomationTabId = naverAutomationTabId;
    // 전용 탭 방식에서는 창을 닫지 않는다. undefined여야 사용자 창 ID 0으로 오인되지 않는다.
    delete draft.naverAutomationWindowId;
    await chrome.storage.session.set({ [DRAFT_KEY]: draft });

    const naverWriteUrl = String(payload.result.naver_write_url || "https://blog.naver.com/GoBlogWrite.naver?categoryNo=42");
    await chrome.tabs.update(naverAutomationTabId, { url: naverWriteUrl, active: true });
    await recordApprovalDispatchTrace({ step: "naver_automation_tab_opened", error: "", batchId: payload.result.batch_id || "" });
  } catch (error) {
    const errorMessage = String(error?.message || "알 수 없는 오류").slice(0, 500);
    const batchId = String(payload?.result?.batch_id || "");
    if (Number.isInteger(naverAutomationWindowId)) await chrome.windows.remove(naverAutomationWindowId).catch(() => undefined);
    else if (Number.isInteger(naverAutomationTabId)) await chrome.tabs.remove(naverAutomationTabId).catch(() => undefined);
    if (Number.isInteger(clipboardPrepTabId)) await chrome.tabs.remove(clipboardPrepTabId).catch(() => undefined);
    await closeImageClipboardDocument();
    if (batchId && claimAcquired) {
      await extensionPublishRequest('/api/coupang/extension/publish/pre-submit-failure', {
        batch_id: batchId,
        error_message: errorMessage,
      }).catch(() => undefined);
    }
    await recordApprovalDispatchTrace({ step: "dispatch_failed", error: errorMessage, batchId });
    throw error;
    }
  } finally {
    approvalDispatchInFlight = false;
  }
}

function startApprovalPolling() {
  chrome.alarms.create(APPROVAL_ALARM, { periodInMinutes: 1 });
  pollApprovedDraft().catch(() => undefined);
}

// 서비스 워커는 알람·메시지·브라우저 이벤트로 수시로 중단·재시작된다.
// 다시 실행되는 즉시 한 번 폴링해, 확장 아이콘을 눌러야만 승인 대기열이 진행되는 문제를 없앤다.
startApprovalPolling();
chrome.runtime.onInstalled.addListener(startApprovalPolling);
chrome.runtime.onStartup.addListener(startApprovalPolling);
chrome.action.onClicked.addListener(() => {
  // 확장 프로그램을 새로고침한 직후에도 사용자가 아이콘 한 번만 클릭하면 즉시 폴링을 재개한다.
  startApprovalPolling();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === APPROVAL_ALARM) pollApprovedDraft().catch(() => undefined);
});

function asText(value, maxLength) {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, maxLength);
}

function safeImageUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const isBlogAutoProxy = url.origin === BLOGAUTO_ORIGIN && (url.pathname.startsWith("/api/coupang/image") || (url.pathname === "/api/image" && url.searchParams.has("url")));
    const isCoupangCdn = /(^|\.)coupangcdn\.com$/i.test(url.hostname) && /\/(?:image|thumbnails)\//i.test(url.pathname);
    if (!isBlogAutoProxy && !isCoupangCdn) return "";
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

function normalizePublishProduct(rawProduct) {
  if (!rawProduct || typeof rawProduct !== "object") return null;
  const productId = asText(rawProduct.product_id, 200);
  const productName = asText(rawProduct.product_name, 500);
  const affiliateUrl = asText(rawProduct.affiliate_url, 2_000);
  const categoryNo = asText(rawProduct.naver_category, 20);
  const normalPrice = Number(rawProduct.normal_price || 0);
  const salePrice = Number(rawProduct.sale_price || 0);
  const conditionalPrice = Number(rawProduct.conditional_price || 0);
  const priceCondition = asText(rawProduct.price_condition, 300);
  if (!productId || !productName || !affiliateUrl.startsWith("https://") || categoryNo !== "42" || !Number.isInteger(normalPrice) || !Number.isInteger(salePrice) || !Number.isInteger(conditionalPrice) || !priceCondition || normalPrice <= 0 || salePrice <= 0 || conditionalPrice <= 0) return null;
  return { platform: "coupang", product_id: productId, product_name: productName, normal_price: normalPrice, sale_price: salePrice, conditional_price: conditionalPrice, price_condition: priceCondition, affiliate_url: affiliateUrl, naver_category: categoryNo };
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
    approvalBatchId: asText(rawDraft?.approvalBatchId, 80),
    preflightOnly: rawDraft?.preflightOnly === true,
    product: normalizePublishProduct(rawDraft?.product),
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

async function autoClickClipboardPrepButton(tabId) {
  await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
  try {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const result = await send(tabId, "Runtime.evaluate", {
        expression: `(() => {
          const button = document.getElementById("copy-image");
          if (!button || button.disabled) return null;
          const rect = button.getBoundingClientRect();
          if (rect.width < 10 || rect.height < 10) return null;
          return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        })()`,
        returnByValue: true,
        awaitPromise: false
      });
      const point = result?.result?.value;
      if (Number.isFinite(point?.x) && Number.isFinite(point?.y)) {
        await click(tabId, point);
        return true;
      }
      await sleep(100);
    }
    throw new Error("원본 이미지 준비 버튼을 자동 클릭할 수 없습니다.");
  } finally {
    await chrome.debugger.detach({ tabId }).catch(() => undefined);
  }
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

async function pressCtrlEnd(tabId) {
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "rawKeyDown", key: "End", code: "End", windowsVirtualKeyCode: 35, nativeVirtualKeyCode: 35, modifiers: 2
  });
  await send(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: "End", code: "End", windowsVirtualKeyCode: 35, nativeVirtualKeyCode: 35, modifiers: 2
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
      const textNodes = []; let node;
      while ((node = walker.nextNode())) {
        if (node.nodeValue) textNodes.push(node);
      }
      const joinedText = textNodes.map((textNode) => textNode.nodeValue || '').join('');
      const matchStart = joinedText.indexOf(target);
      if (matchStart < 0) continue;
      const matchEnd = matchStart + target.length;
      let offset = 0; let startNode = null; let startOffset = 0; let endNode = null; let endOffset = 0;
      for (const textNode of textNodes) {
        const length = (textNode.nodeValue || '').length;
        const nextOffset = offset + length;
        if (!startNode && matchStart >= offset && matchStart < nextOffset) {
          startNode = textNode; startOffset = matchStart - offset;
        }
        if (!endNode && matchEnd >= offset && matchEnd <= nextOffset) {
          endNode = textNode; endOffset = matchEnd - offset;
        }
        offset = nextOffset;
      }
      if (!startNode || !endNode) continue;
      const range = doc.createRange(); range.setStart(startNode, startOffset); range.setEnd(endNode, endOffset);
      const selection = doc.defaultView?.getSelection?.(); if (!selection) continue;
      selection.removeAllRanges(); selection.addRange(range);
      const selectedLength = selection.toString().length;
      if (selectedLength === target.length) return { selected: true, documentIndex, selectedLength };
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

async function waitForPropertyLinkLayerOpen(tabId, attempts = 16) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', { expression: IS_PROPERTY_LINK_LAYER_OPEN, returnByValue: true, awaitPromise: false });
    if (result?.result?.value) return true;
    await sleep(180);
  }
  return false;
}

async function waitForPropertyLinkLayerClosed(tabId, attempts = 16) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', { expression: IS_PROPERTY_LINK_LAYER_OPEN, returnByValue: true, awaitPromise: false });
    if (!result?.result?.value) return true;
    await sleep(180);
  }
  return false;
}

async function waitForRenderedHref(tabId, url, attempts = 16) {
  // SmartEditor는 적용 레이어가 닫힌 뒤 비동기로 a[href]를 반영한다.
  // 즉시 1회만 확인하면 실제 링크가 만들어지는 도중에도 실패로 처리될 수 있으므로,
  // 승인된 URL과 정확히 일치하는 href가 생길 때까지만 짧게 대기한다.
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', {
      expression: hasRenderedHrefExpression(url), returnByValue: true, awaitPromise: false,
    });
    if (result?.result?.value) return true;
    await sleep(250);
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

async function waitForRenderedTextSelection(tabId, text, attempts = 12) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = await send(tabId, 'Runtime.evaluate', { expression: selectRenderedTextExpression(text), returnByValue: true, awaitPromise: false });
    const selected = result?.result?.value;
    if (selected?.selected) return selected;
    await sleep(260);
  }
  return null;
}

async function insertCardlessLink(tabId, url) {
  if (!url) throw new Error("상품 링크가 비어 있습니다.");
  // 실제 성공했던 흐름: URL 문자열을 본문에 먼저 입력하지 않는다.
  // 보이지 않는 단일 시드 문자만 선택한 뒤 SmartEditor 속성 링크에 실제 URL을 적용한다.
  // 이 방식은 화면에서 주소가 두 번 보이던 시기에도 링크 카드 없이 정상 입력된 원본 구현이다.
  const linkSeed = "\u2060";
  await typeText(tabId, linkSeed);
  const selectionResult = await send(tabId, 'Runtime.evaluate', {
    expression: selectRenderedTextExpression(linkSeed), returnByValue: true, awaitPromise: false,
  });
  const selected = selectionResult?.result?.value;
  await recordLinkTrace(tabId, 'after-rendered-dom-selection');
  if (!selected?.selected) throw new Error('복원 링크 입력에서 시드 문자 선택 범위를 만들지 못했습니다. 공개하지 않았습니다.');
  const propertyLinkPoint = await waitForPoint(tabId, FIND_PROPERTY_LINK_BUTTON, 8);
  if (!propertyLinkPoint) throw new Error('복원 링크 입력에서 속성 링크 버튼을 찾지 못했습니다. 공개하지 않았습니다.');
  await click(tabId, propertyLinkPoint);
  await sleep(250);
  await recordLinkTrace(tabId, 'after-property-link-button');
  const layerFilled = await send(tabId, 'Runtime.evaluate', {
    expression: fillPropertyLinkLayerExpression(url), returnByValue: true, awaitPromise: false,
  });
  if (!layerFilled?.result?.value) throw new Error('복원 링크 입력에서 링크 입력칸을 찾지 못했습니다. 공개하지 않았습니다.');
  const applyPoint = await waitForPoint(tabId, FIND_PROPERTY_LINK_APPLY, 10);
  if (!applyPoint) throw new Error('복원 링크 입력에서 링크 적용 버튼이 활성화되지 않았습니다. 공개하지 않았습니다.');
  await click(tabId, applyPoint);
  if (!await waitForPropertyLinkLayerClosed(tabId)) throw new Error('복원 링크 입력에서 링크 레이어가 닫히지 않았습니다. 공개하지 않았습니다.');
  const hrefResult = await send(tabId, 'Runtime.evaluate', {
    expression: hasRenderedHrefExpression(url), returnByValue: true, awaitPromise: false,
  });
  await recordLinkTrace(tabId, 'after-property-link-apply');
  // 원본 구현처럼 링크 레이어가 정상적으로 닫혔으면 본문·이미지 입력을 계속한다.
  // SmartEditor의 DOM a[href] 반영은 비동기이므로 이 단일 확인 실패로 중단하지 않는다.
  const stored = await chrome.storage.session.get(LINK_TRACE_KEY);
  await chrome.storage.session.set({
    [LINK_TRACE_KEY]: {
      ...(stored[LINK_TRACE_KEY] || {}),
      renderedHrefVerified: Boolean(hrefResult?.result?.value),
      invisibleLinkSeedUsed: true,
    },
  });
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

function base64FromArrayBuffer(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return btoa(binary);
}

function fileInputExpression(base64, mimeType, fileName) {
  return `(() => {
    const roots = []; const visited = new Set();
    const visit = (root) => {
      if (!root || visited.has(root)) return;
      visited.add(root); roots.push(root);
      for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} }
      for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} }
    };
    visit(document);
    const inputs = roots.flatMap((root) => [...(root.querySelectorAll?.("input[type='file']") || [])])
      .filter((input) => !input.disabled && input.getAttribute('aria-hidden') !== 'true');
    const target = inputs.find((input) => /image|사진/i.test(input.accept || '')) || inputs[0];
    if (!target) return { ok: false, reason: 'image_input_not_found', inputCount: inputs.length };
    const binary = atob(${JSON.stringify(base64)});
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    const view = target.ownerDocument?.defaultView || window;
    const file = new view.File([bytes], ${JSON.stringify(fileName)}, { type: ${JSON.stringify(mimeType)} });
    const transfer = new view.DataTransfer();
    transfer.items.add(file);
    const setter = Object.getOwnPropertyDescriptor(view.HTMLInputElement.prototype, 'files')?.set;
    if (!setter) return { ok: false, reason: 'file_input_setter_missing' };
    setter.call(target, transfer.files);
    target.dispatchEvent(new view.Event('input', { bubbles: true, composed: true }));
    target.dispatchEvent(new view.Event('change', { bubbles: true, composed: true }));
    return { ok: true, inputCount: inputs.length, accept: String(target.accept || '').slice(0, 120), fileSize: file.size };
  })()`;
}

async function insertOriginalImageFile(tabId, imageUrl) {
  const response = await fetch(imageUrl, { cache: "no-store" });
  if (!response.ok) throw new Error("원본 대표 이미지를 불러오지 못했습니다.");
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) throw new Error("원본 대표 이미지 형식을 확인하지 못했습니다.");
  if (!blob.size || blob.size > 12 * 1024 * 1024) throw new Error("원본 대표 이미지 파일 크기를 확인하지 못했습니다.");
  const mimeType = blob.type === "image/png" ? "image/png" : "image/jpeg";
  const result = await send(tabId, "Runtime.evaluate", {
    expression: fileInputExpression(await base64FromArrayBuffer(await blob.arrayBuffer()), mimeType, `toss-product.${mimeType === "image/png" ? "png" : "jpg"}`),
    returnByValue: true,
    awaitPromise: false,
  });
  const value = result?.result?.value || {};
  if (!value.ok) throw new Error("네이버 사진 입력 요소에 원본 이미지를 전달하지 못했습니다.");
  return value;
}

async function waitForPastedImage(tabId, baselineImages, timeoutMs = 30000) {
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

    // 속성 링크 레이어를 닫은 뒤에는 링크 도구가 포커스를 계속 보유할 수 있다.
    // SmartEditor 본문을 다시 활성화하고 문서 끝으로 이동해야 Ctrl+V가 실제 본문에 전달된다.
    await click(tabId, points.body);
    await sleep(220);
    await pressCtrlEnd(tabId);
    await pressEnter(tabId);
    await sleep(140);
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
    report.bodyInputCommandsCompleted = Boolean(layout.beforeImage && layout.afterImage);
    report.imagePasted = Boolean(imagePasted);
    report.linkApplied = Boolean(linkResult?.invisibleLinkSeedUsed);
    report.linkDomVerified = Boolean(linkResult?.renderedHrefVerified);
    report.shareUrl = layout.shareUrl;
    report.bodyVerificationLimited = !report.bodyPresent;
    report.imageVerificationLimited = !report.imageInserted;
    await recordAutoFillTrace({
      stage: "completed",
      completed: true,
      failed: false,
      titlePresent: Boolean(report.titlePresent),
      bodyPresent: Boolean(report.bodyPresent),
      imageInserted: Boolean(report.imageInserted),
      imagePasted: Boolean(report.imagePasted),
      linkApplied: Boolean(report.linkApplied),
      linkDomVerified: Boolean(report.linkDomVerified),
      bodyInputCommandsCompleted: Boolean(report.bodyInputCommandsCompleted),
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
    if (Number.isInteger(draft?.clipboardPrepTabId) && draft.clipboardPrepTabId !== tabId) {
      await chrome.tabs.remove(draft.clipboardPrepTabId).catch(() => undefined);
    }
    await closeImageClipboardDocument();
  }
}

const NAVER_PUBLISH_PAGE_STATE = `(() => {
  const visited = new Set(); const roots = [];
  const visit = (root) => { if (!root || visited.has(root)) return; visited.add(root); roots.push(root); for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} } for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} } };
  const visible = (el) => { const style = el?.ownerDocument?.defaultView?.getComputedStyle(el); const rect = el?.getBoundingClientRect?.(); return Boolean(style && rect && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width >= 10 && rect.height >= 10); };
  const label = (el) => ((el?.getAttribute?.('aria-label') || '') + ' ' + (el?.getAttribute?.('title') || '') + ' ' + (el?.innerText || el?.textContent || '')).replace(/\\s+/g, ' ').trim();
  const point = (el) => { const rect = el.getBoundingClientRect(); let x = rect.left + rect.width / 2; let y = rect.top + rect.height / 2; let win = el.ownerDocument.defaultView; while (win && win !== win.top) { const frame = win.frameElement; if (!frame) break; const frameRect = frame.getBoundingClientRect(); x += frameRect.left; y += frameRect.top; win = win.parent; } return { x, y }; };
  visit(document);
  const controls = roots.flatMap((root) => [...(root.querySelectorAll?.('button,[role=button],a,[role=radio],label,input') || [])]).filter(visible);
  const text = roots.map((root) => root.body?.innerText || root.textContent || '').join('\\n');
  const publishButtons = controls.filter((el) => {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    const hint = (label(el) + ' ' + (el.className || '') + ' ' + (el.getAttribute('data-log-click') || '') + ' ' + (el.getAttribute('data-click') || '')).toLowerCase();
    return label(el) === '발행' || /(^|[-_\\s])publish($|[-_\\s])|publish-button|write-publish|wp\\.publish/.test(hint);
  });
  const settingsOpen = /전체공개|이웃공개|비공개|발행 설정|공개 설정/.test(text);
  const publicRadio = roots.flatMap((root) => [...(root.querySelectorAll?.('input#open_public') || [])])[0] || null;
  const publicControl = controls.find((el) => /전체공개/.test(label(el))) || (publicRadio?.parentElement && visible(publicRadio.parentElement) ? publicRadio.parentElement : null);
  const publicSelected = Boolean(publicRadio?.checked) || controls.some((el) => /전체공개/.test(label(el)) && (el.checked === true || el.getAttribute('aria-checked') === 'true' || /selected|checked|active|on/.test(String(el.className || ''))));
  const category42Visible = /개이득 쿠팡쇼핑/.test(text) || /categoryNo\\s*[=:]\\s*42/.test(text);
  const category42Url = new URL(location.href).searchParams.get('categoryNo') === '42';
  const category42Verified = category42Visible || category42Url;
  const dialogPublish = publishButtons.find((el) => { const chain = []; for (let node = el; node && chain.length < 8; node = node.parentElement) chain.push(node); return chain.some((node) => /dialog|modal|layer|popup/i.test(String(node?.className || '')) || node?.getAttribute?.('role') === 'dialog'); });
  const topPublish = publishButtons.find((el) => { const rect = el.getBoundingClientRect(); return el !== dialogPublish && rect.top >= 0 && rect.top < 180 && rect.right > window.innerWidth * 0.55; });
  const trigger = topPublish || publishButtons.find((el) => el !== dialogPublish);
  const confirmPublish = publishButtons.find((el) => /confirm[_-]?btn/i.test(String(el.className || ''))) || publishButtons.find((el) => { const rect = el.getBoundingClientRect(); return el !== trigger && label(el) === '발행' && rect.top >= 180; }) || dialogPublish;
  const describe = (el) => el ? { label: label(el).slice(0, 80), className: String(el.className || '').slice(0, 180), top: Math.round(el.getBoundingClientRect().top), left: Math.round(el.getBoundingClientRect().left) } : null;
  return { settingsOpen, publicSelected, category42Verified, trigger: trigger ? point(trigger) : null, publicControl: publicControl ? point(publicControl) : null, confirm: confirmPublish ? point(confirmPublish) : null, publishCandidates: publishButtons.slice(0, 8).map(describe) };
})()`;

async function getNaverPublishPageState(tabId) {
  const result = await send(tabId, 'Runtime.evaluate', { expression: NAVER_PUBLISH_PAGE_STATE, returnByValue: true, awaitPromise: false });
  return result?.result?.value || {};
}

async function waitForNaverPublishState(tabId, predicate, attempts = 16, delayMs = 300) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const state = await getNaverPublishPageState(tabId);
    if (predicate(state)) return state;
    await sleep(delayMs);
  }
  return null;
}

function assertPublishPreconditions(draft, report) {
  if (!draft?.approvalBatchId || !draft?.product) throw new Error('승인 배치 또는 상품 검증 정보를 찾지 못했습니다. 공개하지 않았습니다.');
  if (!report?.titlePresent || !report?.bodyInputCommandsCompleted || !report?.imagePasted || !report?.linkApplied) {
    throw new Error('제목·본문·일반 링크·원본 이미지의 자동 입력 검증을 모두 통과하지 못했습니다. 공개하지 않았습니다.');
  }
  if (report.shareUrl !== draft.product.affiliate_url) throw new Error('본문 링크와 승인된 쉐어링크가 일치하지 않습니다. 공개하지 않았습니다.');
  if (!String(draft.title || '').includes(draft.product.product_name)) throw new Error('제목과 승인 상품명이 일치하지 않습니다. 공개하지 않았습니다.');
}

async function extensionPublishRequest(path, payload) {
  const { [DEVICE_TOKEN_KEY]: deviceToken } = await chrome.storage.local.get(DEVICE_TOKEN_KEY);
  if (!deviceToken) throw new Error('확장 프로그램 장치 연결 정보를 찾지 못했습니다.');
  const response = await fetch(`${BLOGAUTO_ORIGIN}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Naver-Draft-Device': deviceToken },
    body: JSON.stringify(payload),
    cache: 'no-store'
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body?.ok) throw new Error(body?.error || '발행 상태를 서버에 기록하지 못했습니다.');
  return body.result || {};
}

function normalizedNaverPostUrl(rawUrl) {
  try {
    const url = new URL(rawUrl || '');
    if (!/^(?:m\.)?blog\.naver\.com$/i.test(url.hostname)) return '';
    const pathMatch = url.pathname.match(/^\/sijm\/(\d+)$/);
    if (pathMatch) return `https://blog.naver.com/sijm/${pathMatch[1]}`;
    const blogId = url.searchParams.get('blogId') || '';
    const logNo = url.searchParams.get('logNo') || '';
    if (blogId === 'sijm' && /^\d+$/.test(logNo)) return `https://blog.naver.com/sijm/${logNo}`;
  } catch (_) {}
  return '';
}

async function snapshotNaverTabIds() {
  try {
    const tabs = await chrome.tabs.query({});
    return new Set(tabs.map((tab) => Number(tab?.id)).filter(Number.isInteger));
  } catch (_) {
    return new Set();
  }
}

async function waitForPublishedNaverUrl(tabId, tabIdsBeforeClick) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const tab = await chrome.tabs.get(tabId);
      const published = normalizedNaverPostUrl(tab?.url || '');
      if (published) return published;
    } catch (_) {}
    try {
      const tabs = await chrome.tabs.query({});
      for (const tab of tabs) {
        if (!Number.isInteger(tab?.id) || tab.id === tabId || tabIdsBeforeClick?.has(tab.id)) continue;
        const published = normalizedNaverPostUrl(tab?.url || '');
        if (published) return published;
      }
    } catch (_) {}
    await sleep(500);
  }
  return '';
}

const CLICK_NAVER_FINAL_PUBLISH = `(() => {
  const visited = new Set(); const roots = [];
  const visit = (root) => { if (!root || visited.has(root)) return; visited.add(root); roots.push(root); for (const frame of root.querySelectorAll ? root.querySelectorAll('iframe') : []) { try { if (frame.contentDocument) visit(frame.contentDocument); } catch (_) {} } for (const host of root.querySelectorAll ? root.querySelectorAll('*') : []) { try { if (host.shadowRoot) visit(host.shadowRoot); } catch (_) {} } };
  const visible = (el) => { const style = el?.ownerDocument?.defaultView?.getComputedStyle(el); const rect = el?.getBoundingClientRect?.(); return Boolean(style && rect && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width >= 10 && rect.height >= 10); };
  const label = (el) => ((el?.getAttribute?.('aria-label') || '') + ' ' + (el?.getAttribute?.('title') || '') + ' ' + (el?.innerText || el?.textContent || '')).replace(/\\s+/g, ' ').trim();
  visit(document);
  const candidates = roots.flatMap((root) => [...(root.querySelectorAll?.('button,[role=button]') || [])]).filter((el) => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true');
  const button = candidates.find((el) => /confirm[_-]?btn/i.test(String(el.className || '')) && label(el) === '발행') || candidates.find((el) => label(el) === '발행' && el.getBoundingClientRect().top >= 180);
  if (!button) return { clicked: false, reason: 'final_button_not_found' };
  button.scrollIntoView({ block: 'center', inline: 'center' });
  button.focus?.();
  button.click();
  return { clicked: true, className: String(button.className || '').slice(0, 160) };
})()`;

async function clickNaverFinalPublish(tabId) {
  const result = await send(tabId, 'Runtime.evaluate', { expression: CLICK_NAVER_FINAL_PUBLISH, returnByValue: true, awaitPromise: false });
  const value = result?.result?.value || {};
  if (!value.clicked) throw new Error('최종 발행 버튼을 실제로 클릭하지 못했습니다. 공개하지 않았습니다.');
  return value;
}

async function autoPublishApprovedNaver(tabId, draft, report) {
  let attached = false;
  let publishToken = '';
  let publishAttempted = false;
  try {
    assertPublishPreconditions(draft, report);
    await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
    attached = true;
    const initialPublishState = await getNaverPublishPageState(tabId);
    await recordAutoFillTrace({ publishStage: 'initial-controls', publishPageState: initialPublishState });
    let state = initialPublishState?.category42Verified && initialPublishState?.trigger
      ? initialPublishState
      : await waitForNaverPublishState(tabId, (value) => value.category42Verified && value.trigger, 14);
    if (!state?.category42Verified || !state?.trigger) throw new Error('카테고리 42 또는 상단 발행 버튼을 확인하지 못했습니다. 공개하지 않았습니다.');
    await click(tabId, state.trigger);
    state = await waitForNaverPublishState(tabId, (value) => value.settingsOpen, 10);
    await recordAutoFillTrace({ publishStage: 'settings-open-check', publishPageState: state || await getNaverPublishPageState(tabId) });
    if (!state?.settingsOpen) throw new Error('네이버 공개 설정 창을 확인하지 못했습니다. 공개하지 않았습니다.');
    if (!state.publicSelected) {
      if (!state.publicControl) throw new Error('전체공개 선택 항목을 확인하지 못했습니다. 공개하지 않았습니다.');
      await click(tabId, state.publicControl);
      state = await waitForNaverPublishState(tabId, (value) => value.publicSelected, 8);
    }
    if (!state?.publicSelected || !state?.category42Verified || !state?.confirm) {
      throw new Error('전체공개·카테고리 42·최종 발행 버튼 검증을 통과하지 못했습니다. 공개하지 않았습니다.');
    }
    const begun = await extensionPublishRequest('/api/coupang/extension/publish/begin', { batch_id: draft.approvalBatchId, product: draft.product });
    publishToken = String(begun.publish_token || '');
    if (!publishToken) throw new Error('발행 중복 방지 잠금을 받지 못했습니다. 공개하지 않았습니다.');
    await recordApprovalDispatchTrace({ step: 'publish-clicking', error: '', batchId: draft.approvalBatchId });
    const tabIdsBeforeClick = await snapshotNaverTabIds();
    await clickNaverFinalPublish(tabId);
    const settingsClosed = await waitForNaverPublishState(tabId, (value) => !value.settingsOpen, 12, 500);
    if (!settingsClosed) throw new Error('최종 발행 버튼 클릭 뒤 설정 창이 닫히지 않았습니다. 공개하지 않았습니다.');
    publishAttempted = true;
    const naverPostUrl = await waitForPublishedNaverUrl(tabId, tabIdsBeforeClick);
    if (!naverPostUrl) throw new Error('발행 버튼 클릭 뒤 공개 URL을 확인하지 못했습니다.');
    await extensionPublishRequest('/api/coupang/extension/publish/result', { batch_id: draft.approvalBatchId, publish_token: publishToken, outcome: 'PUBLISHED', naver_post_url: naverPostUrl });
    await recordApprovalDispatchTrace({ step: 'published', error: '', batchId: draft.approvalBatchId, naverPostUrl });
    return { status: 'PUBLISHED', naverPostUrl };
  } catch (error) {
    const message = String(error?.message || '알 수 없는 발행 오류').slice(0, 500);
    await recordAutoFillTrace({ publishStage: 'failed', publishError: message }).catch(() => undefined);
    if (publishToken) {
      const outcome = publishAttempted ? 'PUBLISH_UNKNOWN' : 'FAILED_PRE_SUBMIT';
      await extensionPublishRequest('/api/coupang/extension/publish/result', { batch_id: draft.approvalBatchId, publish_token: publishToken, outcome, error_message: message }).catch(() => undefined);
      await recordApprovalDispatchTrace({ step: outcome === 'PUBLISH_UNKNOWN' ? 'publish_unknown' : 'publish_blocked', error: message, batchId: draft.approvalBatchId });
      if (publishAttempted) return { status: 'PUBLISH_UNKNOWN', error: message };
    } else {
      await recordApprovalDispatchTrace({ step: 'publish_blocked', error: message, batchId: draft?.approvalBatchId || '' });
    }
    throw error;
  } finally {
    if (attached) await chrome.debugger.detach({ tabId }).catch(() => undefined);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target === "offscreen" || message?.type === "CLIPBOARD_PREPARE_IMAGE") return false;
  (async () => {
    if (message?.type === "COUPANG_PUBLISHER_GET_APPROVAL_TRACE") {
      if (!isBlogAutoSender(sender)) throw new Error("허용되지 않은 확장 프로그램 진단 요청입니다.");
      const stored = await chrome.storage.local.get("coupangNaverPublisherApprovalTrace");
      sendResponse({ ok: true, trace: stored.coupangNaverPublisherApprovalTrace || null });
      return;
    }

    if (message?.type === "COUPANG_PUBLISHER_RESUME_APPROVAL_POLL") {
      if (!isBlogAutoSender(sender)) throw new Error("허용되지 않은 승인 폴링 재개 요청입니다.");
      startApprovalPolling();
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "COUPANG_PUBLISHER_PAIR_DEVICE") {
      if (!isBlogAutoSender(sender)) throw new Error("허용되지 않은 확장 프로그램 연결 요청입니다.");
      const token = asText(message.deviceToken, 200);
      if (token.length < 24) throw new Error("확장 프로그램 연결 토큰이 올바르지 않습니다.");
      const pairState = { [DEVICE_TOKEN_KEY]: token };
      if (Number.isInteger(sender.tab?.id)) pairState[PAIR_TAB_ID_KEY] = sender.tab.id;
      await chrome.storage.local.set(pairState);
      startApprovalPolling();
      sendResponse({ ok: true });
      return;
    }

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
      try {
        const report = await autoFillNaver(sender.tab.id, draft);
        const publish = draft.preflightOnly
          ? await extensionPublishRequest('/api/coupang/extension/publish/preflight-success', { batch_id: draft.approvalBatchId })
          : await autoPublishApprovedNaver(sender.tab.id, draft, report);
        await chrome.storage.session.remove(DRAFT_KEY);
        sendResponse({ ok: true, report: { ...report, publish, preflightOnly: Boolean(draft.preflightOnly) } });
      } catch (error) {
        const errorMessage = String(error?.message || "자동 입력 또는 공개 전 검증 실패").slice(0, 500);
        if (draft.approvalBatchId) {
          await extensionPublishRequest('/api/coupang/extension/publish/pre-submit-failure', {
            batch_id: draft.approvalBatchId,
            error_message: errorMessage,
          }).catch(() => undefined);
        }
        await chrome.storage.session.remove(DRAFT_KEY);
        throw error;
      } finally {
        // 이 식별자는 pollApprovedDraft가 만든 전용 자동화 탭에만 저장된다.
        // 사용자가 직접 연 네이버·관리자·작업 탭과 일반 Chrome 창은 절대 닫지 않는다.
        const automationTabId = Number(draft?.naverAutomationTabId);
        const automationWindowId = Number(draft?.naverAutomationWindowId);
        if (Number.isInteger(automationTabId) && automationTabId === sender.tab.id) {
          if (Number.isInteger(automationWindowId) && automationWindowId > 0) await chrome.windows.remove(automationWindowId).catch(() => undefined);
          else await chrome.tabs.remove(automationTabId).catch(() => undefined);
        }
      }
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
