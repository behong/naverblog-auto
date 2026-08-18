$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\Administrator\code\naverblog-auto'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Replace-ExactlyOnce([string]$Path, [string]$Find, [string]$Replace) {
  $source = [System.IO.File]::ReadAllText((Resolve-Path $Path))
  $count = [regex]::Matches($source, [regex]::Escape($Find)).Count
  if ($count -ne 1) { throw "Expected exactly one match in $Path; found $count." }
  $updated = $source.Replace($Find, $Replace)
  [System.IO.File]::WriteAllText((Resolve-Path $Path), $updated, $utf8NoBom)
}

$worker = 'extension\naver-draft-assistant\service-worker.js'
Replace-ExactlyOnce $worker @'
const LINK_TRACE_KEY = "naverDraftAssistantLinkTrace";
'@ @'
const LINK_TRACE_KEY = "naverDraftAssistantLinkTrace";
const AUTOFILL_TRACE_KEY = "naverDraftAssistantAutoFillTrace";
'@
Replace-ExactlyOnce $worker @'
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
'@ @'
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function recordAutoFillTrace(patch) {
  const stored = await chrome.storage.session.get(AUTOFILL_TRACE_KEY);
  const previous = stored[AUTOFILL_TRACE_KEY] || {};
  await chrome.storage.session.set({
    [AUTOFILL_TRACE_KEY]: { ...previous, ...patch, updatedAt: Date.now() }
  });
}
'@
Replace-ExactlyOnce $worker @'
async function autoFillNaver(tabId, draft) {
  await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
  try {
    await dismissExistingDraftDialog(tabId);
    const points = await findEditorPoints(tabId);
'@ @'
async function autoFillNaver(tabId, draft) {
  await recordAutoFillTrace({ stage: "starting", completed: false, failed: false });
  await chrome.debugger.attach({ tabId }, DEBUGGER_VERSION);
  try {
    await dismissExistingDraftDialog(tabId);
    const points = await findEditorPoints(tabId);
    await recordAutoFillTrace({ stage: "editor-points-found" });
'@
Replace-ExactlyOnce $worker @'
    const linkedDisplayText = await insertCardlessLink(tabId, layout.shareUrl);
    if (layout.afterImage) {
'@ @'
    const linkedDisplayText = await insertCardlessLink(tabId, layout.shareUrl);
    await recordAutoFillTrace({ stage: "property-link-applied" });
    if (layout.afterImage) {
'@
Replace-ExactlyOnce $worker @'
      await insertBody(tabId, layout.afterImage);
    }
    // 네이버의 비동기 붙여넣기는 마지막 입력 명령이 실행된 위치를 사용한다.
'@ @'
      await insertBody(tabId, layout.afterImage);
    }
    await recordAutoFillTrace({ stage: "after-link-text-inserted" });
    // 네이버의 비동기 붙여넣기는 마지막 입력 명령이 실행된 위치를 사용한다.
'@
Replace-ExactlyOnce $worker @'
    await pasteImage(tabId);
    // 이후에는 어떤 키 입력도 보내지 않는다. 늦은 이미지 처리도 URL 바로 아래에 고정된다.
'@ @'
    await pasteImage(tabId);
    await recordAutoFillTrace({ stage: "image-paste-command-sent" });
    // 이후에는 어떤 키 입력도 보내지 않는다. 늦은 이미지 처리도 URL 바로 아래에 고정된다.
'@
Replace-ExactlyOnce $worker @'
    report.bodyVerificationLimited = !report.bodyPresent;
    report.imageVerificationLimited = !report.imageInserted;
    return report;
  } finally {
'@ @'
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
'@
Replace-ExactlyOnce $worker @'
    if (message?.type === "NAVER_GET_DRAFT") {
'@ @'
    if (message?.type === "NAVER_GET_AUTOFILL_TRACE") {
      if (!isNaverEditorSender(sender)) throw new Error("네이버 글쓰기 화면에서만 사용할 수 있습니다.");
      const stored = await chrome.storage.session.get(AUTOFILL_TRACE_KEY);
      sendResponse({ ok: true, trace: stored[AUTOFILL_TRACE_KEY] || null });
      return;
    }

    if (message?.type === "NAVER_GET_DRAFT") {
'@
Replace-ExactlyOnce $worker @'
      await autoFillNaver(sender.tab.id, draft);
      await chrome.storage.session.remove(DRAFT_KEY);
      sendResponse({ ok: true });
'@ @'
      const report = await autoFillNaver(sender.tab.id, draft);
      await chrome.storage.session.remove(DRAFT_KEY);
      sendResponse({ ok: true, report });
'@

$editor = 'extension\naver-draft-assistant\naver-editor.js'
Replace-ExactlyOnce $editor @'
  let linkApplicationTrace = null;
  try {
    const traceResponse = await chrome.runtime.sendMessage({ type: "NAVER_GET_LINK_TRACE" });
    if (traceResponse?.ok) linkApplicationTrace = traceResponse.trace || null;
  } catch {
    // 진단 본문은 현재 페이지 구조만으로도 유효하므로 추적 수신 실패는 무시한다.
  }
'@ @'
  let linkApplicationTrace = null;
  let autoFillTrace = null;
  try {
    const [linkResponse, fillResponse] = await Promise.all([
      chrome.runtime.sendMessage({ type: "NAVER_GET_LINK_TRACE" }),
      chrome.runtime.sendMessage({ type: "NAVER_GET_AUTOFILL_TRACE" })
    ]);
    if (linkResponse?.ok) linkApplicationTrace = linkResponse.trace || null;
    if (fillResponse?.ok) autoFillTrace = fillResponse.trace || null;
  } catch {
    // 진단 본문은 현재 페이지 구조만으로도 유효하므로 추적 수신 실패는 무시한다.
  }
'@
Replace-ExactlyOnce $editor @'
    linkApplicationTrace,
    documents: documents.map((root, documentIndex) => {
'@ @'
    linkApplicationTrace,
    autoFillTrace,
    documents: documents.map((root, documentIndex) => {
'@
Replace-ExactlyOnce $editor @'
    renderPanel({
      title: "자동 입력 완료",
      text: "제목·본문·원본 대표 이미지 입력을 요청했습니다. 이미지와 본문을 확인한 뒤 발행은 직접 진행해 주세요.",
      tone: "success"
    });
'@ @'
    const report = response.report || {};
    const verificationNote = report.bodyVerificationLimited || report.imageVerificationLimited
      ? " 제목은 확인됐고, 본문·이미지는 네이버 내부 렌더링 특성상 화면에서 확인해 주세요."
      : " 제목·본문·이미지 반영 확인을 마쳤습니다.";
    renderPanel({
      title: "자동 입력 완료",
      text: `제목·본문·원본 대표 이미지 입력을 요청했습니다.${verificationNote} 발행은 직접 진행해 주세요.`,
      tone: "success",
      actionLabel: "비민감 진단 정보 복사",
      onAction: async (event) => {
        try {
          await copyEditorDiagnostics();
          const button = event.currentTarget;
          button.textContent = "비민감 진단 정보 복사 완료";
          button.disabled = true;
          button.style.opacity = "0.72";
          button.style.cursor = "default";
        } catch {
          event.currentTarget.textContent = "진단 복사 실패 · 다시 시도";
        }
      }
    });
'@

$manifest = 'extension\naver-draft-assistant\manifest.json'
$manifestText = [System.IO.File]::ReadAllText((Resolve-Path $manifest))
if ($manifestText -notmatch '"version"\s*:\s*"0\.4\.5"') { throw 'Expected manifest version 0.4.5 was not found.' }
$manifestText = $manifestText -replace '"version"\s*:\s*"0\.4\.5"', '"version": "0.4.6"'
[System.IO.File]::WriteAllText((Resolve-Path $manifest), $manifestText, $utf8NoBom)

node --check $worker
node --check $editor
node -e "JSON.parse(require('fs').readFileSync('extension/naver-draft-assistant/manifest.json','utf8')); console.log('manifest JSON OK')"
python -m pytest tests -q
Write-Output 'PATCH_0.4.6_OK'
