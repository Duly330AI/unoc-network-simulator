# Start the FastAPI backend (http://127.0.0.1:5001).
# Requires: postgres (scripts/start-postgres.ps1) and the Go traffic engine
# (scripts/start-engine.ps1) to be running. Wraps the verified command from
# docs/local_start.md — no destructive operations.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Prefer .venv, fall back to the audit venv name.
$python = @('.venv\Scripts\python.exe', '.venv-audit\Scripts\python.exe') |
    ForEach-Object { Join-Path $repoRoot $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    Write-Host 'No venv found. Create one first (see docs/local_start.md):' -ForegroundColor Yellow
    Write-Host '  python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}

# Defaults match docs/local_start.md; respect values already set by the caller / .env.
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'postgresql://unoc:unocpw@localhost:5432/unocdb' }
if (-not $env:UNOC_DEV_FEATURES) { $env:UNOC_DEV_FEATURES = '1' }
if (-not $env:UNOC_DISABLE_RELOAD) { $env:UNOC_DISABLE_RELOAD = '1' }

& $python run.py
