const REQUEST_ATTR = "data-coupang-naver-publisher-request";
const RESPONSE_ATTR = "data-coupang-naver-publisher-response";
const READY_ATTR = "data-coupang-naver-publisher-ready";
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
    await chrome.runtime.sendMessage({ type: "COUPANG_PUBLISHER_RESUME_APPROVAL_POLL" });
  } catch {
    // 승인 폴링 재개 실패는 관리자 화면에서의 페어링과 독립적으로 처리한다.
  }
}

async function processRequest() {
  const raw = document.documentElement.getAttribute(REQUEST_ATTR);
  if (!raw) return;
  try {
    const request = JSON.parse(raw);
    if (!request?.requestId || request.requestId === lastRequestId) return;
    if (request.type !== "PAIR_COUPANG_PUBLISHER_DEVICE" && request.type !== "GET_COUPANG_PUBLISHER_TRACE") return;
    lastRequestId = request.requestId;
    const response = await chrome.runtime.sendMessage(
      request.type === "PAIR_COUPANG_PUBLISHER_DEVICE"
        ? { type: "COUPANG_PUBLISHER_PAIR_DEVICE", deviceToken: request.deviceToken }
        : { type: "COUPANG_PUBLISHER_GET_APPROVAL_TRACE" },
    );
    writeResponse({ requestId: request.requestId, ...response });
  } catch {
    writeResponse({ requestId: lastRequestId, ok: false, error: "쿠팡 발행 확장과 통신하지 못했습니다." });
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
