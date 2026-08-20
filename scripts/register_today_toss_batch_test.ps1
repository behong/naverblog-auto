$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_today_toss_batch_test.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$userName = "$env:USERDOMAIN\$env:USERNAME"
$testTaskName = 'NaverBlogAuto-TossTestRelease20m'
$regularTaskName = 'NaverBlogAuto-TossRelease20m'

if (-not (Test-Path $runner)) { throw "테스트 실행기를 찾지 못했습니다: $runner" }
$now = Get-Date
$minutesToNext = 20 - ($now.Minute % 20)
if ($minutesToNext -lt 2) { $minutesToNext += 20 }
$start = $now.AddMinutes($minutesToNext)
$startText = $start.ToString('HH:mm')
$taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`""

Disable-ScheduledTask -TaskName $regularTaskName | Out-Null
& schtasks.exe /Create /TN $testTaskName /TR $taskCommand /SC MINUTE /MO 20 /ST $startText /RU $userName /RL LIMITED /IT /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    Enable-ScheduledTask -TaskName $regularTaskName | Out-Null
    throw '오늘 테스트 반복 작업 등록에 실패했습니다.'
}

Write-Output 'TODAY_TEST_TASK_REGISTERED=TRUE'
Write-Output "TODAY_TEST_FIRST_RELEASE=$startText"
Write-Output 'TODAY_TEST_MAX_ITEMS=10'
Write-Output 'REGULAR_RELEASE_TASK_TEMPORARILY_DISABLED=TRUE'
