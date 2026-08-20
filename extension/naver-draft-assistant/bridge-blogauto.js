const REQUEST_ATTR = "data-naver-draft-assistant-request";
const RESPONSE_ATTR = "data-naver-draft-assistant-response";
const READY_ATTR = "data-naver-draft-assistant-ready";
let lastRequestId = "";

function writeResponse(payload) {
  document.documentElement.setAttribute(RESPONSE_ATTR, JSON.stringify(payload));
}

function setReady() {
  document.documentElement.setAttribute(READY_ATTR, JSON.stringify({
    ready: true,
    version: chrome.runtime.getManifest().version,
    updatedAt: Date.now(),
  }));
}

async function resumeApprovalPolling() {
  try {
    await chrome.runtime.sendMessage({ type: "BLOGAUTO_RESUME_APPROVAL_POLL" });
  } catch {
    // 사이트에서의 초안 작성 기능은 승인 폴링 재개 실패와 독립적으로 동작한다.
  }
}

async function processRequest() {
  const raw = document.documentElement.getAttribute(REQUEST_ATTR);
  if (!raw) return;
  try {
    const request = JSON.parse(raw);
    if (!request?.requestId || request.requestId === lastRequestId) return;
    if (request.type !== "STORE_DRAFT" && request.type !== "PAIR_DEVICE" && request.type !== "GET_APPROVAL_TRACE") return;
    lastRequestId = request.requestId;
    const response = await chrome.runtime.sendMessage(
      request.type === "PAIR_DEVICE"
        ? { type: "BLOGAUTO_PAIR_DEVICE", deviceToken: request.deviceToken }
        : request.type === "GET_APPROVAL_TRACE"
          ? { type: "BLOGAUTO_GET_APPROVAL_TRACE" }
          : { type: "BLOGAUTO_STORE_DRAFT", draft: request.draft },
    );
    writeResponse({ requestId: request.requestId, ...response });
  } catch {
    writeResponse({ requestId: lastRequestId, ok: false, error: "확장 프로그램과 통신하지 못했습니다." });
  }
}

new MutationObserver((records) => {
  if (records.some((record) => record.type === "attributes" && record.attributeName === REQUEST_ATTR)) {
    processRequest();
  }
}).observe(document.documentElement, { attributes: true, attributeFilter: [REQUEST_ATTR] });

setReady();
resumeApprovalPolling();
processRequest();
