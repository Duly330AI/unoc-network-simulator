# Start the Go Traffic Engine (HTTP :8080). MANDATORY before the backend.
# Wraps the verified command from docs/local_start.md — no destructive operations.
$repoRoot = Split-Path -Parent $PSScriptRoot
$engineDir = Join-Path $repoRoot 'engine-go'
$exe = Join-Path $engineDir 'bin\traffic-engine.exe'

if (-not (Test-Path $exe)) {
    Write-Host 'traffic-engine.exe not found. Build it first:' -ForegroundColor Yellow
    Write-Host '  cd engine-go; go build -o bin/traffic-engine.exe ./cmd/traffic-engine/'
    exit 1
}

# DATABASE_URL default inside the engine already matches the compose Postgres.
Set-Location $engineDir
& $exe
