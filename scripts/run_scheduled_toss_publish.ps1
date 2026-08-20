param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Prepare', 'PrepareWindow', 'Release')]
    [string]$Mode,
    [string]$WindowKey = '',
    [int]$Count = 0
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'logs'
$logPath = Join-Path $logDirectory 'scheduled-toss-publish.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if ($Mode -eq 'PrepareWindow' -and ([string]::IsNullOrWhiteSpace($WindowKey) -or $Count -lt 1 -or $Count -gt 10)) {
    throw '시간대별 초안 준비에는 유효한 WindowKey와 Count가 필요합니다.'
}

function Write-ScheduleLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') [$Mode] $Message"
    Add-Content -Path $logPath -Value $line -Encoding utf8
    Write-Output $line
}

try {
    Set-Location $projectRoot
    $serviceRunning = docker compose ps --status running --services | Select-String -Quiet '^naverblog-auto$'
    if (-not $serviceRunning) { throw '서비스 컨테이너가 실행 중이 아닙니다.' }
    if ($Mode -eq 'PrepareWindow') {
        $output = docker compose exec -T -e PYTHONPATH=/app naverblog-auto python scripts/prepare_toss_draft_window.py --window-key $WindowKey --count $Count 2>&1
    }
    else {
        $scriptName = if ($Mode -eq 'Prepare') { 'prepare_daily_toss_publish_queue.py' } else { 'release_next_scheduled_toss_item.py' }
        $output = docker compose exec -T -e PYTHONPATH=/app naverblog-auto python "scripts/$scriptName" 2>&1
    }
    if ($LASTEXITCODE -ne 0) { throw ($output | Out-String).Trim() }
    Write-ScheduleLog ($output | Out-String).Trim()
}
catch {
    Write-ScheduleLog ("FAILED: $($_.Exception.Message)")
    exit 1
}
