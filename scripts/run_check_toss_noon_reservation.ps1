$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'
try {
    $result = docker compose exec -T -e PYTHONPATH=/app naverblog-auto python scripts/check_toss_noon_reservation.py
    if ($LASTEXITCODE -ne 0) {
        throw "container_check_exit_$LASTEXITCODE"
    }
    Add-Content -Path (Join-Path $projectRoot 'logs\toss-noon-reservation-check.log') -Value "$timestamp $result"
    Write-Output $result
} catch {
    $safeMessage = $_.Exception.Message -replace '[\r\n]+', ' '
    Add-Content -Path (Join-Path $projectRoot 'logs\toss-noon-reservation-check.log') -Value "$timestamp {\"check\":\"toss_noon_reservation\",\"ok\":false,\"error\":\"$safeMessage\"}"
    throw
}
