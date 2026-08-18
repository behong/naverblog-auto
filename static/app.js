const sourceText = document.querySelector("#sourceText");
const productPrice = document.querySelector("#productPrice");
const generateButton = document.querySelector("#generateButton");
const errorMessage = document.querySelector("#errorMessage");
const resultSection = document.querySelector("#resultSection");
const postTitle = document.querySelector("#postTitle");
const postBody = document.querySelector("#postBody");
const postTags = document.querySelector("#postTags");
const productImage = document.querySelector("#productImage");
const imagePlaceholder = document.querySelector("#imagePlaceholder");
const imageNote = document.querySelector("#imageNote");
const copyImageButton = document.querySelector("#copyImageButton");
const copyImageForNaverButton = document.querySelector("#copyImageForNaverButton");
const downloadImageButton = document.querySelector("#downloadImageButton");
const copyAllButton = document.querySelector("#copyAllButton");
const openNaverButton = document.querySelector("#openNaverButton");
const copyMessage = document.querySelector("#copyMessage");
const sendToExtensionButton = document.querySelector("#sendToExtensionButton");
const extensionMessage = document.querySelector("#extensionMessage");
const toast = document.querySelector("#toast");

let currentImageUrl = "";
let currentImageProxyUrl = "";
let currentImageReady = false;
let extensionReady = false;
let draftPreparedForNaver = false;
let pendingNaverWindow = null;
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2300);
}

async function copyText(text, successMessage = "복사했어요.") {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(text);
  } catch {
    const field = document.createElement("textarea");
    field.value = text;
    field.style.position = "fixed";
    field.style.left = "-10000px";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("텍스트 복사가 차단됐습니다.");
  }
  showToast(successMessage);
}

function bodyAndTagsText() {
  const body = postBody.value
    .split("\n")
    .filter((line) => line.trim() !== "[이미지 영역]")
    .join("\n")
    .trim();
  return `${body}\n\n${postTags.value.trim()}`;
}

function setExtensionStatus(message, ready = extensionReady) {
  extensionReady = ready;
  if (sendToExtensionButton) {
    sendToExtensionButton.disabled = false;
    sendToExtensionButton.setAttribute("aria-disabled", "false");
  }
  if (extensionMessage) extensionMessage.textContent = message;
}

function extensionDraft() {
  return {
    title: postTitle.value.trim(),
    body: postBody.value
      .split("\n")
      .filter((line) => line.trim() !== "[이미지 영역]")
      .join("\n")
      .trim(),
    tags: postTags.value.trim(),
    imageUrl: currentImageProxyUrl ? new URL(currentImageProxyUrl, window.location.origin).href : "",
  };
}

const EXTENSION_REQUEST_ATTR = "data-naver-draft-assistant-request";
const EXTENSION_RESPONSE_ATTR = "data-naver-draft-assistant-response";
const EXTENSION_READY_ATTR = "data-naver-draft-assistant-ready";

function requestExtensionAvailability() {
  try {
    const state = JSON.parse(document.documentElement.getAttribute(EXTENSION_READY_ATTR) || "{}");
    if (state.ready) setExtensionStatus("확장 프로그램 연결 완료 · 초안을 네이버에 안전하게 전달할 수 있어요.", true);
  } catch {
    // The extension has not supplied a usable readiness record yet.
  }
}

function storeDraftInExtension(draft) {
  return new Promise((resolve) => {
    const requestId = crypto.randomUUID();
    const timeout = setTimeout(() => {
      observer.disconnect();
      resolve({ ok: false, error: "확장 프로그램이 응답하지 않았습니다. Chrome 확장 프로그램을 새로고침한 뒤 이 페이지를 Ctrl+Shift+R로 새로고침해 주세요." });
    }, 2500);
    const observer = new MutationObserver(() => {
      try {
        const response = JSON.parse(document.documentElement.getAttribute(EXTENSION_RESPONSE_ATTR) || "{}");
        if (response.requestId !== requestId) return;
        clearTimeout(timeout);
        observer.disconnect();
        resolve(response);
      } catch {
        // Wait for the extension to write a complete response.
      }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: [EXTENSION_RESPONSE_ATTR] });
    document.documentElement.setAttribute(EXTENSION_REQUEST_ATTR, JSON.stringify({ type: "STORE_DRAFT", requestId, draft }));
  });
}

new MutationObserver((records) => {
  if (records.some((record) => record.attributeName === EXTENSION_READY_ATTR)) requestExtensionAvailability();
}).observe(document.documentElement, { attributes: true, attributeFilter: [EXTENSION_READY_ATTR] });

window.addEventListener("DOMContentLoaded", () => {
  requestExtensionAvailability();
  setTimeout(requestExtensionAvailability, 500);
  setTimeout(requestExtensionAvailability, 1500);
});

function setLoading(loading) {
  generateButton.disabled = loading;
  generateButton.querySelector(".button-label").textContent = loading
    ? "상품 정보를 읽고 있어요…"
    : "블로그 글 만들기";
}

function setImage(imageUrl, warning) {
  currentImageUrl = imageUrl || "";
  currentImageProxyUrl = "";
  currentImageReady = false;
  productImage.hidden = true;
  imagePlaceholder.hidden = false;
  copyImageButton.disabled = true;
  copyImageForNaverButton.disabled = true;
  downloadImageButton.hidden = true;

  if (!currentImageUrl) {
    productImage.removeAttribute("src");
    imagePlaceholder.textContent = "대표 이미지를 자동으로 찾지 못했어요. 토스 상품 화면에서 사진을 직접 저장해 주세요.";
    imageNote.textContent = warning || "상품 페이지 구조에 따라 이미지가 제공되지 않을 수 있어요.";
    return;
  }

  currentImageProxyUrl = `/api/image?url=${encodeURIComponent(currentImageUrl)}`;
  imagePlaceholder.textContent = "대표 이미지를 확인하고 있어요…";
  imageNote.textContent = warning || "토스 상품 페이지의 대표 이미지를 불러오는 중입니다.";
  productImage.src = currentImageProxyUrl;
}

productImage.addEventListener("load", () => {
  currentImageReady = true;
  productImage.hidden = false;
  imagePlaceholder.hidden = true;
  imageNote.textContent = "대표 이미지 확인 완료 · 2번 버튼으로 실제 이미지를 복사할 수 있어요.";
  copyImageButton.disabled = false;
  copyImageForNaverButton.disabled = false;
  downloadImageButton.hidden = false;
  downloadImageButton.href = `${currentImageProxyUrl}&download=1`;
});

productImage.addEventListener("error", () => {
  currentImageReady = false;
  productImage.hidden = true;
  imagePlaceholder.hidden = false;
  imagePlaceholder.textContent = "이미지를 불러오지 못했어요. 아래 ‘텍스트만 복사’를 이용하거나 토스 상품 화면에서 사진을 저장해 주세요.";
  imageNote.textContent = "이미지 주소가 변경됐거나 토스 서버에서 가져오기를 차단했습니다.";
  copyImageButton.disabled = true;
  copyImageForNaverButton.disabled = true;
  downloadImageButton.hidden = true;
});

async function generate() {
  errorMessage.hidden = true;
  copyMessage.textContent = "";
  setLoading(true);
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: sourceText.value, price: productPrice.value }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "글을 만들지 못했습니다.");

    const result = payload.result;
    postTitle.value = result.generated.title;
    postBody.value = result.generated.body;
    postTags.value = result.generated.tags.map((tag) => `#${tag}`).join(" ");
    setImage(result.metadata.images?.[0], result.metadata_warning);
    resultSection.hidden = false;
    resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    errorMessage.textContent = error.message;
    errorMessage.hidden = false;
  } finally {
    setLoading(false);
  }
}

generateButton.addEventListener("click", generate);

sendToExtensionButton?.addEventListener("click", async () => {
  const draft = extensionDraft();
  if (!draft.title || !draft.body) {
    setExtensionStatus("먼저 상품 정보를 분석해 제목과 본문을 만든 뒤 다시 눌러 주세요.", extensionReady);
    return;
  }
  if (!currentImageReady || !draft.imageUrl) {
    setExtensionStatus("원본 대표 이미지를 아직 확인하지 못했습니다. 이미지가 표시되고 ‘대표 이미지 확인 완료’ 안내가 나온 뒤 1번을 눌러 주세요. 이미지 없는 글은 전달하지 않습니다.", extensionReady);
    return;
  }
  setExtensionStatus("원본 대표 이미지를 클립보드에 준비하고 초안을 전달하고 있어요…", true);
  const imageCopied = await copyProductImage({ announce: false });
  if (!imageCopied) {
    setExtensionStatus("원본 대표 이미지를 클립보드에 준비하지 못했습니다. 대표 이미지 아래의 ‘이미지 복사’를 한 번 직접 누른 뒤 다시 1번을 눌러 주세요.", true);
    return;
  }
  const response = await storeDraftInExtension(draft);
  if (!response.ok) {
    draftPreparedForNaver = false;
    setExtensionStatus(response.error || "초안을 확장 프로그램으로 전달하지 못했습니다.", true);
    return;
  }
  draftPreparedForNaver = true;
  setExtensionStatus("초안 준비 완료 · 원본 대표 이미지도 클립보드에 준비했습니다. 2번 네이버 열기를 누르면 이미지 클립보드를 유지한 채 자동 입력을 시작합니다.", true);
});

productPrice.addEventListener("input", () => {
  productPrice.value = productPrice.value.replace(/[^0-9]/g, "");
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.querySelector(`#${button.dataset.copyTarget}`);
    copyText(target.value, "제목을 복사했어요.").catch(() => showToast("복사하지 못했어요."));
  });
});

copyAllButton.addEventListener("click", async () => {
  try {
    await copyText(bodyAndTagsText(), "본문·태그를 복사했어요.");
    copyMessage.textContent = "본문·태그 복사 완료! 네이버에서 이미지 아래를 클릭하고 Ctrl+V로 붙여넣으세요.";
  } catch {
    copyMessage.textContent = "자동 복사가 차단됐어요. 본문을 직접 선택해 복사해 주세요.";
  }
});

async function copyProductImage({ announce = true } = {}) {
  if (!currentImageReady || !currentImageProxyUrl) return false;
  try {
    const response = await fetch(currentImageProxyUrl);
    if (!response.ok) throw new Error("이미지를 불러오지 못했습니다.");
    const sourceBlob = await response.blob();
    const bitmap = await createImageBitmap(sourceBlob);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0);
    const pngBlob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!pngBlob) throw new Error("이미지 변환에 실패했습니다.");
    await navigator.clipboard.write([new ClipboardItem({ "image/png": pngBlob })]);
    if (announce) {
      copyMessage.textContent = "원본 대표 이미지를 클립보드에 준비했어요. 네이버 본문의 원하는 위치에서 Ctrl+V를 한 번 누르세요.";
      showToast("원본 대표 이미지를 클립보드에 준비했어요.");
    }
    return true;
  } catch (error) {
    if (announce) {
      copyMessage.textContent = "브라우저가 이미지 복사를 차단했어요. 대표 이미지 아래의 ‘이미지 복사’를 한 번 직접 눌러 다시 시도해 주세요.";
      showToast("이미지 복사가 차단됐어요.");
    }
    return false;
  }
}

copyImageButton.addEventListener("click", copyProductImage);
copyImageForNaverButton.addEventListener("click", copyProductImage);

function copyTitleForNaverLaunch(title) {
  const field = document.createElement("textarea");
  field.value = title;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.left = "-10000px";
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand("copy");
  field.remove();
  return copied;
}

openNaverButton.addEventListener("click", () => {
  const title = postTitle.value.trim();
  if (!title) {
    copyMessage.textContent = "먼저 상품 정보를 입력해 제목을 만든 뒤 다시 눌러 주세요.";
    return;
  }
  // 1번에서 확장 프로그램으로 초안을 전달한 경우에는 원본 이미지 PNG가 이미 클립보드에 있다.
  // 여기서 제목 텍스트를 복사하면 이미지가 덮어써져 네이버가 상품 미리보기 카드로 처리할 수 있다.
  if (extensionReady && draftPreparedForNaver) {
    showToast("원본 대표 이미지를 유지한 채 네이버 글쓰기 창을 열어요.");
    copyMessage.textContent = "원본 대표 이미지 클립보드를 유지했습니다. 네이버에서 제목·본문·이미지가 자동 입력됩니다.";
    return;
  }
  const copied = copyTitleForNaverLaunch(title);
  if (copied) {
    showToast("제목을 복사하고 네이버 글쓰기 창을 열어요.");
    copyMessage.textContent = "제목을 복사했어요. 네이버 제목 칸을 클릭한 뒤 Ctrl+V로 붙여넣으세요.";
  } else {
    copyMessage.textContent = "네이버 글쓰기 창을 열었지만 제목 복사가 차단됐어요. 제목 옆 ‘제목 복사’ 버튼을 눌러 다시 복사해 주세요.";
  }
});
