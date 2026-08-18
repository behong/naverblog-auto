$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\Administrator\code\naverblog-auto'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Replace-ExactlyOnce([string]$Path, [string]$Find, [string]$Replace) {
  $source = [System.IO.File]::ReadAllText((Resolve-Path $Path))
  $count = [regex]::Matches($source, [regex]::Escape($Find)).Count
  if ($count -ne 1) { throw "Expected exactly one match in $Path; found $count." }
  [System.IO.File]::WriteAllText((Resolve-Path $Path), $source.Replace($Find, $Replace), $utf8NoBom)
}
function Replace-RegexExactlyOnce([string]$Path, [string]$Pattern, [string]$Replacement) {
  $source = [System.IO.File]::ReadAllText((Resolve-Path $Path))
  $matches = [regex]::Matches($source, $Pattern)
  if ($matches.Count -ne 1) { throw "Expected exactly one regex match in $Path; found $($matches.Count)." }
  $updated = [regex]::Replace($source, $Pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $Replacement }, 1)
  [System.IO.File]::WriteAllText((Resolve-Path $Path), $updated, $utf8NoBom)
}

$worker = 'extension\naver-draft-assistant\service-worker.js'
Replace-RegexExactlyOnce $worker '(?s)(    if \(layout\.afterImage\) \{\s*await pressEnter\(tabId\);\s*await pressEnter\(tabId\);\s*await insertBody\(tabId, layout\.afterImage\);\s*\})' '$1\r\n    await recordAutoFillTrace({ stage: "after-link-text-inserted" });'
Replace-ExactlyOnce $worker @'
    await pasteImage(tabId);
'@ @'
    await pasteImage(tabId);
    await recordAutoFillTrace({ stage: "image-paste-command-sent" });
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
'@ @'
  let linkApplicationTrace = null;
  let autoFillTrace = null;
'@
Replace-ExactlyOnce $editor @'
    if (traceResponse?.ok) linkApplicationTrace = traceResponse.trace || null;
'@ @'
    if (traceResponse?.ok) linkApplicationTrace = traceResponse.trace || null;
    const fillResponse = await chrome.runtime.sendMessage({ type: "NAVER_GET_AUTOFILL_TRACE" });
    if (fillResponse?.ok) autoFillTrace = fillResponse.trace || null;
'@
Replace-ExactlyOnce $editor @'
    linkApplicationTrace,
    documents: documents.map((root, documentIndex) => {
'@ @'
    linkApplicationTrace,
    autoFillTrace,
    documents: documents.map((root, documentIndex) => {
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
