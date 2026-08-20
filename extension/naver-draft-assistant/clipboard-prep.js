const BLOGAUTO_ORIGIN = "https://blogauto.hongzi.us";
const port = chrome.runtime.connect({ name: "naver-draft-clipboard-prep" });
const copyButton = document.getElementById("copy-image");
const status = document.getElementById("status");
let pendingRequest = null;

function safeImageUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.origin === BLOGAUTO_ORIGIN && url.pathname.startsWith("/api/image") ? url.href : "";
  } catch {
    return "";
  }
}

async function copyOriginalImage(imageUrl) {
  const safeUrl = safeImageUrl(imageUrl);
  if (!safeUrl) throw new Error("허용되지 않은 이미지 주소입니다.");
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
}

copyButton.addEventListener("click", async () => {
  if (!pendingRequest) return;
  const request = pendingRequest;
  copyButton.disabled = true;
  status.textContent = "원본 이미지를 준비하고 있습니다.";
  try {
    await copyOriginalImage(request.imageUrl);
    status.textContent = "원본 이미지 준비가 완료되었습니다. 네이버 입력을 계속합니다.";
    port.postMessage({ requestId: request.requestId, ok: true });
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
    port.postMessage({ requestId: request.requestId, ok: false, error: message });
    pendingRequest = null;
  }
});

port.onMessage.addListener((message) => {
  if (message?.type !== "CLIPBOARD_PREPARE_IMAGE" || !message.requestId) return;
  pendingRequest = { requestId: message.requestId, imageUrl: message.imageUrl, autoAttempt: Boolean(message.autoAttempt) };
  copyButton.disabled = false;
  status.textContent = pendingRequest.autoAttempt ? "원본 이미지를 자동으로 준비하고 있습니다." : "버튼을 한 번 눌러 원본 이미지를 준비해 주세요.";
  copyButton.focus();
});
