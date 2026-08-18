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

async function processRequest() {
  const raw = document.documentElement.getAttribute(REQUEST_ATTR);
  if (!raw) return;
  try {
    const request = JSON.parse(raw);
    if (!request?.requestId || request.requestId === lastRequestId || request.type !== "STORE_DRAFT") return;
    lastRequestId = request.requestId;
    const response = await chrome.runtime.sendMessage({
      type: "BLOGAUTO_STORE_DRAFT",
      draft: request.draft,
    });
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
processRequest();
