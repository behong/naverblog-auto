param(
    [Parameter(Mandatory = $true)]
    [string]$TestDate
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_scheduled_toss_publish.ps1'
$taskName = 'NaverBlogAuto-TossDraftTest5m'
$logDirectory = Join-Path $projectRoot 'logs'
$statePath = Join-Path $logDirectory "toss-draft-test-$TestDate.json"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Stop-ThisTestTask {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

$today = (Get-Date).ToString('yyyy-MM-dd')
if ($today -ne $TestDate) {
    Stop-ThisTestTask
    exit 0
}

$state = @{ completed = 0 }
if (Test-Path $statePath) {
    try { $state = Get-Content $statePath -Raw | ConvertFrom-Json } catch { $state = @{ completed = 0 } }
}
$completed = [int]($state.completed)
if ($completed -ge 5) {
    Stop-ThisTestTask
    exit 0
}

$nextNumber = $completed + 1
try {
    & $runner -Mode PrepareWindow -WindowKey "test-$nextNumber" -Count 1
    if ($LASTEXITCODE -ne 0) { throw "초안 준비 실행이 실패했습니다. 결과 코드: $LASTEXITCODE" }
    @{ completed = $nextNumber; updated_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -Path $statePath -Encoding utf8
    if ($nextNumber -ge 5) { Stop-ThisTestTask }
}
catch {
    Add-Content -Path (Join-Path $logDirectory 'scheduled-toss-publish.log') -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') [PrepareWindowTest] FAILED: $($_.Exception.Message)" -Encoding utf8
    exit 1
}
