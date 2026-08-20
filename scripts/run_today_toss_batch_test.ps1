$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'logs'
$logPath = Join-Path $logDirectory 'scheduled-toss-publish.log'
$testTaskName = 'NaverBlogAuto-TossTestRelease20m'
$regularTaskName = 'NaverBlogAuto-TossRelease20m'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-TestLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') [TodayTestRelease] $Message"
    Add-Content -Path $logPath -Value $line -Encoding utf8
    Write-Output $line
}

try {
    Set-Location $projectRoot
    $serviceRunning = docker compose ps --status running --services | Select-String -Quiet '^naverblog-auto$'
    if (-not $serviceRunning) { throw '서비스 컨테이너가 실행 중이 아닙니다.' }
    $raw = docker compose exec -T -e PYTHONPATH=/app naverblog-auto python scripts/release_next_scheduled_toss_item.py 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($raw | Out-String).Trim() }
    $jsonLine = ($raw | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
    if (-not $jsonLine) { throw '릴리스 결과 JSON을 찾지 못했습니다.' }
    $result = $jsonLine | ConvertFrom-Json
    Write-TestLog ($jsonLine.Trim())
    $queue = $result.queue
    $completed = [int]$queue.PUBLISHED + [int]$queue.FAILED_PRE_SUBMIT + [int]$queue.PUBLISH_UNKNOWN + [int]$queue.SKIPPED
    if ([int]$queue.QUEUED -eq 0 -and [int]$queue.RELEASED -eq 0 -and $completed -ge 10) {
        Enable-ScheduledTask -TaskName $regularTaskName | Out-Null
        Unregister-ScheduledTask -TaskName $testTaskName -Confirm:$false
        Write-TestLog 'MAX_10_TEST_COMPLETED; REGULAR_RELEASE_TASK_REENABLED'
    }
}
catch {
    Write-TestLog ("FAILED: $($_.Exception.Message)")
    exit 1
}
