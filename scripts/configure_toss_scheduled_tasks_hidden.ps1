$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$hiddenRunner = Join-Path $PSScriptRoot 'run_scheduled_toss_publish_hidden.vbs'
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$backupDirectory = Join-Path $projectRoot 'logs\scheduled-task-backups'

if (-not (Test-Path -LiteralPath $hiddenRunner -PathType Leaf)) {
    throw "숨김 실행기 파일을 찾지 못했습니다: $hiddenRunner"
}
if (-not (Test-Path -LiteralPath $wscript -PathType Leaf)) {
    throw "Windows Script Host를 찾지 못했습니다: $wscript"
}

New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like 'NaverBlogAuto-Toss*' } | Sort-Object TaskName
if (-not $tasks) {
    throw '토스 예약 작업을 찾지 못했습니다.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$changed = @()
foreach ($task in $tasks) {
    $action = @($task.Actions)[0]
    if (-not $action -or [string]::IsNullOrWhiteSpace($action.Arguments)) {
        throw "실행 인수를 확인하지 못했습니다: $($task.TaskName)"
    }
    if ($action.Execute -notmatch 'powershell\.exe$') {
        throw "기대하지 않은 실행 파일입니다: $($task.TaskName) ($($action.Execute))"
    }
    if ($action.Arguments -notmatch 'run_scheduled_toss_publish\.ps1') {
        throw "토스 예약 실행기를 확인하지 못했습니다: $($task.TaskName)"
    }

    $backupPath = Join-Path $backupDirectory "$($task.TaskName)-$timestamp.xml"
    Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-File -LiteralPath $backupPath -Encoding utf8

    $hiddenArguments = ('"{0}" {1}' -f $hiddenRunner, $action.Arguments)
    $hiddenAction = New-ScheduledTaskAction -Execute $wscript -Argument $hiddenArguments
    $settings = $task.Settings
    $settings.Hidden = $true

    Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Action $hiddenAction -Settings $settings | Out-Null
    $changed += [PSCustomObject]@{
        TaskName = $task.TaskName
        Execute = $wscript
        Hidden = $true
        Backup = $backupPath
    }
}

$changed | Format-Table -AutoSize
