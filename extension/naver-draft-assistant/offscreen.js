const BLOGAUTO_ORIGIN = "https://blogauto.hongzi.us";

function safeImageUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.origin === BLOGAUTO_ORIGIN && url.pathname.startsWith("/api/image") ? url.href : "";
  } catch {
    return "";
  }
}

async function writeOriginalImageToClipboard(imageUrl) {
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
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("PNG 클립보드 쓰기 기능을 사용할 수 없습니다.");
  }
  await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.target !== "offscreen" || message?.type !== "OFFSCREEN_WRITE_IMAGE") return false;
  writeOriginalImageToClipboard(message.imageUrl)
    .then(() => sendResponse({ ok: true }))
    .catch((error) => sendResponse({ ok: false, error: String(error?.message || "이미지 클립보드 준비 실패") }));
  return true;
});
