$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_scheduled_toss_publish.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$userName = "$env:USERDOMAIN\$env:USERNAME"

function Register-TossTask([string]$TaskName, [string]$Mode, [string]$Schedule, [string]$StartTime, [string]$Modifier = '') {
    $taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Mode $Mode"
    $args = @('/Create', '/TN', $TaskName, '/TR', $taskCommand, '/SC', $Schedule, '/ST', $StartTime, '/RU', $userName, '/RL', 'LIMITED', '/IT', '/F')
    if ($Modifier) { $args += @('/MO', $Modifier) }
    & schtasks.exe @args | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "작업 등록 실패: $TaskName" }
}

if (-not (Test-Path $runner)) { throw "예약 실행 스크립트를 찾지 못했습니다: $runner" }
Set-Location $projectRoot

Register-TossTask -TaskName 'NaverBlogAuto-TossPrepare0800' -Mode 'Prepare' -Schedule 'DAILY' -StartTime '08:00'
Register-TossTask -TaskName 'NaverBlogAuto-TossRelease20m' -Mode 'Release' -Schedule 'MINUTE' -StartTime '08:20' -Modifier '20'

Write-Output 'SCHEDULE_REGISTERED=TRUE'
Write-Output 'PREPARE_TASK=NaverBlogAuto-TossPrepare0800 DAILY 08:00'
Write-Output 'RELEASE_TASK=NaverBlogAuto-TossRelease20m EVERY_20_MINUTES_FROM_08:20_MAX_10'
Write-Output 'REQUIREMENTS=INTERACTIVE_WINDOWS_SESSION_DOCKER_RUNNING_CHROME_EXTENSION_ACTIVE'
