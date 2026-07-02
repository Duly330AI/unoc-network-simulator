# Start only the PostgreSQL container from docker-compose.yml (idempotent).
# Wraps the verified command from docs/local_start.md — no destructive operations.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
docker compose up -d postgres
docker inspect --format 'unoc-postgres health: {{.State.Health.Status}}' unoc-postgres
