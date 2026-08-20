$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_scheduled_toss_publish.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$userName = "$env:USERDOMAIN\$env:USERNAME"

function Register-DraftWindowTask([string]$TaskName, [string]$StartTime, [string]$WindowKey, [int]$Count) {
    $taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Mode PrepareWindow -WindowKey $WindowKey -Count $Count"
    $args = @('/Create', '/TN', $TaskName, '/TR', $taskCommand, '/SC', 'DAILY', '/ST', $StartTime, '/RU', $userName, '/RL', 'LIMITED', '/IT', '/F')
    & schtasks.exe @args | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "작업 등록 실패: $TaskName" }
}

if (-not (Test-Path $runner)) { throw "예약 실행 스크립트를 찾지 못했습니다: $runner" }
Set-Location $projectRoot

# 기존 08:00 일괄 준비는 시간대별 준비와 중복되므로 중지한다.
Disable-ScheduledTask -TaskName 'NaverBlogAuto-TossPrepare0800' -ErrorAction SilentlyContinue | Out-Null
Register-DraftWindowTask -TaskName 'NaverBlogAuto-TossDrafts0700' -StartTime '07:00' -WindowKey 'morning' -Count 4
Register-DraftWindowTask -TaskName 'NaverBlogAuto-TossDrafts1200' -StartTime '12:00' -WindowKey 'midday' -Count 2
Register-DraftWindowTask -TaskName 'NaverBlogAuto-TossDrafts1800' -StartTime '18:00' -WindowKey 'evening' -Count 4

Write-Output 'SCHEDULE_REGISTERED=TRUE'
Write-Output 'DRAFT_WINDOW_1=07:00 count=4'
Write-Output 'DRAFT_WINDOW_2=12:00 count=2'
Write-Output 'DRAFT_WINDOW_3=18:00 count=4'
Write-Output 'PUBLISHING=DISABLED_UNTIL_TELEGRAM_APPROVAL'
Write-Output 'REQUIREMENTS=LOCAL_PC_ON_DOCKER_RUNNING'
