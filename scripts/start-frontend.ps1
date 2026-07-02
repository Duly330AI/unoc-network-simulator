# Start the Vue frontend dev server (http://127.0.0.1:5173).
# Wraps the verified command from docs/local_start.md — no destructive operations.
$repoRoot = Split-Path -Parent $PSScriptRoot
$feDir = Join-Path $repoRoot 'unoc-frontend-v2'
Set-Location $feDir

if (-not (Test-Path (Join-Path $feDir 'node_modules'))) {
    Write-Host 'node_modules missing — running npm ci first...' -ForegroundColor Yellow
    npm ci --no-audit --no-fund
}

# Explicit IPv4 bind: default binding can end up ::1-only, breaking IPv4 tooling.
npx vite --host 127.0.0.1 --port 5173 --strictPort
