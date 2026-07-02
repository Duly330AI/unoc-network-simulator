param(
    [switch]$DryRun,
    [switch]$Force
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$repoRootFull = [System.IO.Path]::GetFullPath($repoRoot)

function Get-ProcessDetails {
    param([int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue

    [pscustomobject]@{
        ProcessName = if ($process) { $process.ProcessName } else { '<unknown>' }
        CommandLine = if ($cim -and $cim.CommandLine) { $cim.CommandLine } else { '<unavailable>' }
    }
}

function Test-IsUnocProcess {
    param([string]$CommandLine)

    if (-not $CommandLine -or $CommandLine -eq '<unavailable>') {
        return $false
    }

    if ($CommandLine.IndexOf($repoRootFull, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return $true
    }

    $normalized = $CommandLine.Replace('/', '\')
    $markers = @(
        '\engine-go\',
        '\run.py',
        '\unoc-frontend-v2\',
        '\scripts\start-engine.ps1',
        '\scripts\start-backend.ps1',
        '\scripts\start-frontend.ps1'
    )

    foreach ($marker in $markers) {
        if ($normalized.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }

    return $false
}

function Stop-ComposePostgres {
    Write-Host 'PostgreSQL compose service' -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host 'DRY RUN: would run docker compose stop postgres from repo root.'
        return
    }

    Push-Location $repoRootFull
    try {
        docker compose stop postgres
    }
    finally {
        Pop-Location
    }
}

function Get-PortOwner {
    param([int]$Port)

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Stop-MatchedProcess {
    param(
        [string]$Name,
        [int]$Port
    )

    $listener = Get-PortOwner -Port $Port
    if (-not $listener) {
        Write-Host "SKIP: $Name port $Port is not listening."
        return
    }

    $pidToStop = [int]$listener.OwningProcess
    $details = Get-ProcessDetails -ProcessId $pidToStop
    $isUnoc = Test-IsUnocProcess -CommandLine $details.CommandLine

    Write-Host "Port $Port ($Name): PID $pidToStop, process $($details.ProcessName)"
    Write-Host "Command line: $($details.CommandLine)"

    if (-not $isUnoc) {
        Write-Host "SKIP: PID $pidToStop was not confidently matched to this UNOC work copy." -ForegroundColor Yellow
        return
    }

    if ($DryRun) {
        Write-Host "DRY RUN: would stop PID $pidToStop for $Name." -ForegroundColor Green
        return
    }

    if (-not $Force) {
        $answer = Read-Host "Stop PID $pidToStop for $Name? Type Y to continue"
        if ($answer -ne 'Y') {
            Write-Host "SKIP: user did not confirm stopping PID $pidToStop."
            return
        }
    }

    Stop-Process -Id $pidToStop -ErrorAction Stop
    Write-Host "STOPPED: PID $pidToStop for $Name." -ForegroundColor Green
}

Write-Host "UNOC controlled shutdown" -ForegroundColor Cyan
Write-Host "Repo root: $repoRootFull"
if ($DryRun) { Write-Host 'Mode: dry run' -ForegroundColor Yellow }
elseif ($Force) { Write-Host 'Mode: force' -ForegroundColor Yellow }
else { Write-Host 'Mode: confirm before stopping matched local processes' }
Write-Host ''

Stop-ComposePostgres
Write-Host ''

$targets = @(
    @{ Name = 'Go Traffic Engine'; Port = 8080 },
    @{ Name = 'FastAPI backend'; Port = 5001 },
    @{ Name = 'Vue/Vite frontend'; Port = 5173 }
)

foreach ($target in $targets) {
    Stop-MatchedProcess -Name $target.Name -Port $target.Port
    Write-Host ''
}