param(
    [Parameter(Mandatory = $true)]
    [string]$TestDate
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'NaverBlogAuto-TossPublishTest5m'
$logDirectory = Join-Path $projectRoot 'logs'
$logPath = Join-Path $logDirectory 'scheduled-toss-publish.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Stop-ThisTestTask {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

function Write-TestLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') [ReleaseTest5m] $Message"
    Add-Content -Path $logPath -Value $line -Encoding utf8
    Write-Output $line
}

if ((Get-Date).ToString('yyyy-MM-dd') -ne $TestDate) {
    Stop-ThisTestTask
    exit 0
}

try {
    Set-Location $projectRoot
    $serviceRunning = docker compose ps --status running --services | Select-String -Quiet '^naverblog-auto$'
    if (-not $serviceRunning) { throw '서비스 컨테이너가 실행 중이 아닙니다.' }

    $output = docker compose exec -T -e PYTHONPATH=/app naverblog-auto python scripts/release_next_scheduled_toss_item.py 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($output | Out-String).Trim() }
    Write-TestLog ($output | Out-String).Trim()
}
catch {
    Write-TestLog ("FAILED: $($_.Exception.Message)")
    exit 1
}
