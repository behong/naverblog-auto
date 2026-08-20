$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_today_toss_draft_test.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$userName = "$env:USERDOMAIN\$env:USERNAME"
$taskName = 'NaverBlogAuto-TossDraftTest5m'
$testDate = (Get-Date).ToString('yyyy-MM-dd')
$statePath = Join-Path $projectRoot "logs\toss-draft-test-$testDate.json"

if (-not (Test-Path $runner)) { throw "테스트 실행 스크립트를 찾지 못했습니다: $runner" }
Remove-Item $statePath -Force -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

$startAt = (Get-Date).AddMinutes(1)
$startTime = $startAt.ToString('HH:mm')
$taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -TestDate $testDate"
$args = @('/Create', '/TN', $taskName, '/TR', $taskCommand, '/SC', 'MINUTE', '/MO', '5', '/ST', $startTime, '/RU', $userName, '/RL', 'LIMITED', '/IT', '/F')
& schtasks.exe @args | Out-Host
if ($LASTEXITCODE -ne 0) { throw "오늘 전용 5분 간격 테스트 작업 등록에 실패했습니다: $taskName" }

Write-Output 'TODAY_DRAFT_TEST_REGISTERED=TRUE'
Write-Output "TASK_NAME=$taskName"
Write-Output "START_TIME=$startTime"
Write-Output 'INTERVAL_MINUTES=5'
Write-Output 'MAX_PREPARED_DRAFTS=5'
Write-Output 'PUBLISHING=DISABLED'
