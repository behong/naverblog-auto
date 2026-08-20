$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$targets = @(
    (Join-Path $PSScriptRoot 'run_scheduled_toss_publish.ps1'),
    (Join-Path $PSScriptRoot 'register_daily_toss_schedule.ps1'),
    (Join-Path $PSScriptRoot 'run_today_toss_batch_test.ps1'),
    (Join-Path $PSScriptRoot 'register_today_toss_batch_test.ps1')
)
foreach ($target in $targets) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($target, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) {
        $parseErrors | ForEach-Object { Write-Output "PARSER_ERROR|${target}|line=$($_.Extent.StartLineNumber)|$($_.Message)" }
        exit 1
    }
}
Write-Output 'SCHEDULE_POWERSHELL_SYNTAX_OK'
