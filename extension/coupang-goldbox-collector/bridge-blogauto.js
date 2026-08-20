const REQUEST_ATTR = "data-coupang-goldbox-collector-request";
const RESPONSE_ATTR = "data-coupang-goldbox-collector-response";
const READY_ATTR = "data-coupang-goldbox-collector-ready";
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

async function processRequest() {
  const raw = document.documentElement.getAttribute(REQUEST_ATTR);
  if (!raw) return;
  try {
    const request = JSON.parse(raw);
    if (!request?.requestId || request.requestId === lastRequestId) return;
    if (request.type !== "PAIR_COUPANG_COLLECTOR_DEVICE") return;
    lastRequestId = request.requestId;
    const response = await chrome.runtime.sendMessage({ type: "COUPANG_COLLECTOR_PAIR_DEVICE", deviceToken: request.deviceToken });
    writeResponse({ requestId: request.requestId, ...response });
  } catch {
    writeResponse({ requestId: lastRequestId, ok: false, error: "쿠팡 수집기와 통신하지 못했습니다." });
  }
}

new MutationObserver((records) => {
  if (records.some((record) => record.type === "attributes" && record.attributeName === REQUEST_ATTR)) {
    processRequest();
  }
}).observe(document.documentElement, { attributes: true, attributeFilter: [REQUEST_ATTR] });

setReady();
processRequest();
