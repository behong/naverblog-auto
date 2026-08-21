const BLOGAUTO_ORIGIN = "https://blogauto.hongzi.us";
const port = chrome.runtime.connect({ name: "naver-draft-clipboard-prep" });
let portConnected = true;
const copyButton = document.getElementById("copy-image");
const status = document.getElementById("status");
let pendingRequest = null;

async function recordClipboardTrace(step, details = {}) {
  try {
    const stored = await chrome.storage.local.get("coupangClipboardTrace");
    const entries = Array.isArray(stored.coupangClipboardTrace) ? stored.coupangClipboardTrace : [];
    entries.push({ at: new Date().toISOString(), step, ...details });
    await chrome.storage.local.set({ coupangClipboardTrace: entries.slice(-50) });
  } catch {
    // 진단 기록 실패가 이미지 준비를 중단시키지 않도록 한다.
  }
}

function imageAddressSummary(value) {
  try {
    const url = new URL(String(value || ""));
    return { host: url.hostname, path: url.pathname, hasQuery: Boolean(url.search) };
  } catch {
    return { host: "", path: "", hasQuery: false };
  }
}

function safeImageUrl(value) {
  try {
    const url = new URL(String(value || ""));
    const isBlogAutoProxy = url.origin === BLOGAUTO_ORIGIN && (url.pathname.startsWith("/api/coupang/image") || (url.pathname === "/api/image" && url.searchParams.has("url")));
    const isCoupangCdn = /(^|\.)coupangcdn\.com$/i.test(url.hostname) && /\/(?:image|thumbnails)\//i.test(url.pathname);
    return isBlogAutoProxy || isCoupangCdn ? url.href : "";
  } catch {
    return "";
  }
}

function sendResult(payload) {
  if (!portConnected) return;
  try { port.postMessage(payload); } catch { /* 탭 종료 직후에는 응답을 생략한다. */ }
}

port.onDisconnect.addListener(() => {
  portConnected = false;
  void recordClipboardTrace("port_disconnected");
});
void recordClipboardTrace("page_connected");

async function copyOriginalImage(imageUrl) {
  const safeUrl = safeImageUrl(imageUrl);
  if (!safeUrl) {
    await recordClipboardTrace("image_url_rejected", imageAddressSummary(imageUrl));
    throw new Error("허용되지 않은 이미지 주소입니다.");
  }
  await recordClipboardTrace("image_fetch_start", imageAddressSummary(safeUrl));
  const response = await fetch(safeUrl, { cache: "no-store" });
  if (!response.ok) throw new Error("원본 대표 이미지를 불러오지 못했습니다.");
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) throw new Error("원본 대표 이미지 형식을 확인하지 못했습니다.");
  let png = blob;
  if (blob.type !== "image/png") {
    const bitmap = await createImageBitmap(blob);
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("원본 이미지 변환 캔버스를 만들지 못했습니다.");
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    png = await canvas.convertToBlob({ type: "image/png" });
  }
  await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  await recordClipboardTrace("clipboard_write_success", { mime: blob.type, width: png.width || 0, height: png.height || 0 });
}

copyButton.addEventListener("click", async () => {
  if (!pendingRequest) return;
  const request = pendingRequest;
  void recordClipboardTrace("button_click", { requestId: request.requestId, autoAttempt: Boolean(request.autoAttempt) });
  copyButton.disabled = true;
  status.textContent = "원본 이미지를 준비하고 있습니다.";
  try {
    await copyOriginalImage(request.imageUrl);
    status.textContent = "원본 이미지 준비가 완료되었습니다. 네이버 입력을 계속합니다.";
    await recordClipboardTrace("request_success", { requestId: request.requestId, portConnected });
    sendResult({ requestId: request.requestId, ok: true });
    pendingRequest = null;
  } catch (error) {
    const message = String(error?.message || "이미지 클립보드 준비 실패");
    // 자동 클릭이 브라우저의 사용자 활성화 정책에 막혀도 발행을 실패로 끝내지 않는다.
    // 실제 버튼 클릭으로 같은 요청을 한 번만 안전하게 재시도할 수 있게 유지한다.
    if (request.autoAttempt) {
      pendingRequest = { ...request, autoAttempt: false };
      copyButton.disabled = false;
      status.textContent = "자동 이미지 준비가 제한되었습니다. 파란색 버튼을 한 번 누르면 계속합니다.";
      return;
    }
    status.textContent = `준비하지 못했습니다: ${message}`;
    await recordClipboardTrace("request_failure", { requestId: request.requestId, error: message, portConnected });
    sendResult({ requestId: request.requestId, ok: false, error: message });
    pendingRequest = null;
  }
});

port.onMessage.addListener((message) => {
  if (message?.type !== "CLIPBOARD_PREPARE_IMAGE" || !message.requestId) return;
  pendingRequest = { requestId: message.requestId, imageUrl: message.imageUrl, autoAttempt: Boolean(message.autoAttempt) };
  void recordClipboardTrace("request_received", { requestId: message.requestId, ...imageAddressSummary(message.imageUrl) });
  copyButton.disabled = false;
  status.textContent = pendingRequest.autoAttempt ? "원본 이미지를 자동으로 준비하고 있습니다." : "버튼을 한 번 눌러 원본 이미지를 준비해 주세요.";
  copyButton.focus();
});
