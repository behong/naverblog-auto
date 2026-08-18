[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $projectDir ".env"
$total10OpenApiEnvFile = Join-Path $projectDir "..\total-10shop-260514\.env.docker.cutover"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env is missing. Copy .env.example and configure the server values."
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $envFile -Encoding utf8) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $settings[$Matches[1]] = $Matches[2].Trim()
    }
}

foreach ($requiredKey in @("DATABASE_URL", "AUTOMATION_API_TOKEN")) {
    if (-not $settings.ContainsKey($requiredKey) -or [string]::IsNullOrWhiteSpace($settings[$requiredKey])) {
        throw "Configure $requiredKey in .env first."
    }
}

if (-not (Test-Path -LiteralPath $total10OpenApiEnvFile)) {
    throw "Total10 .env.docker.cutover is missing: $total10OpenApiEnvFile"
}

$openApiSettings = @{}
foreach ($line in Get-Content -LiteralPath $total10OpenApiEnvFile -Encoding utf8) {
    if ($line -match '^\s*(TOSS_OPEN_API_[A-Za-z0-9_]*)=(.*)$') {
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $openApiSettings[$Matches[1]] = $value
    }
}

foreach ($requiredKey in @("TOSS_OPEN_API_ACCESS_KEY", "TOSS_OPEN_API_SECRET_KEY")) {
    if (-not $openApiSettings.ContainsKey($requiredKey) -or
        [string]::IsNullOrWhiteSpace($openApiSettings[$requiredKey])) {
        throw "Configure $requiredKey in Total10 .env.docker.cutover first."
    }
}
if ($openApiSettings.ContainsKey("TOSS_OPEN_API_ENV") -and
    $openApiSettings["TOSS_OPEN_API_ENV"] -ne "production") {
    throw "TOSS_OPEN_API_ENV in Total10 .env.docker.cutover must be production."
}
$openApiSettings["TOSS_OPEN_API_ENV"] = "production"
foreach ($entry in $openApiSettings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
}
Write-Host "Loaded $($openApiSettings.Count) TOSS_OPEN_API_* settings from Total10 .env.docker.cutover."

Push-Location $projectDir
try {
    docker compose --env-file $envFile config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose configuration validation failed with exit code $LASTEXITCODE."
    }
    if ($SkipBuild) {
        docker compose --env-file $envFile up -d --force-recreate naverblog-auto
    }
    else {
        docker compose --env-file $envFile up -d --build --force-recreate naverblog-auto
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose deployment failed with exit code $LASTEXITCODE."
    }
    docker compose --env-file $envFile ps naverblog-auto
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the deployed container (exit code $LASTEXITCODE)."
    }
    $healthUri = "http://127.0.0.1:$($settings['NAVERBLOG_PORT'])/health"
    $health = $null
    $lastHealthError = $null
    for ($attempt = 1; $attempt -le 15; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 5
            if ($health.status -eq "ok" -and
                $health.automation.database -eq "ok" -and
                $health.toss_open_api.status -eq "ok" -and
                $health.toss_open_api.environment -eq "production") {
                break
            }
            $lastHealthError = "status=$($health.status), database=$($health.automation.database), toss_open_api=$($health.toss_open_api.status), environment=$($health.toss_open_api.environment)"
        }
        catch {
            $lastHealthError = $_.Exception.Message
        }
        Write-Host "Waiting for service readiness ($attempt/15)..."
        Start-Sleep -Seconds 2
    }
    if ($health.status -ne "ok" -or
        $health.automation.database -ne "ok" -or
        $health.toss_open_api.status -ne "ok" -or
        $health.toss_open_api.environment -ne "production") {
        throw "Post-deploy health check failed: $lastHealthError`nRun: docker compose logs --tail 100 naverblog-auto"
    }
    Write-Host "Deployment complete: application, PostgreSQL, and production Toss Open API are healthy."
}
finally {
    Pop-Location
}
