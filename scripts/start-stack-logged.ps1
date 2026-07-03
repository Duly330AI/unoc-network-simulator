param(
    [switch]$NoFrontend,
    [switch]$NoBackend,
    [switch]$NoEngine,
    [switch]$IncludeOptionalGoServices,
    [switch]$SkipHealthCheck
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$repoRootFull = [System.IO.Path]::GetFullPath($repoRoot)
$logsDir = Join-Path $repoRootFull 'logs'
$defaultDatabaseUrl = 'postgresql://unoc:unocpw@localhost:5432/unocdb'

function Get-PortOwner {
    param([int]$Port)

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ProcessDetails {
    param([int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue

    [pscustomobject]@{
        ProcessName = if ($process) { $process.ProcessName } else { '<unknown>' }
        CommandLine = if ($cim -and $cim.CommandLine) { $cim.CommandLine } else { '<unavailable>' }
    }
}

function Show-ExistingListener {
    param(
        [string]$Name,
        [int]$Port,
        [object]$Listener
    )

    $details = Get-ProcessDetails -ProcessId $Listener.OwningProcess
    Write-Host "SKIP: $Name already has a listener on port $Port." -ForegroundColor Yellow
    Write-Host "  PID: $($Listener.OwningProcess)"
    Write-Host "  Process: $($details.ProcessName)"
    Write-Host "  Command line: $($details.CommandLine)"
    Write-Host '  Use .\scripts\status-stack.ps1 to inspect the stack or .\scripts\stop-stack.ps1 for controlled shutdown.'
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$WorkingDirectory,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$StdoutLog,
        [string]$StderrLog,
        [string]$PidFile
    )

    $listener = Get-PortOwner -Port $Port
    if ($listener) {
        Show-ExistingListener -Name $Name -Port $Port -Listener $listener
        return
    }

    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        Write-Host "SKIP: $Name working directory not found: $WorkingDirectory" -ForegroundColor Yellow
        return
    }

    if (-not (Get-Command $FilePath -ErrorAction SilentlyContinue) -and -not (Test-Path -LiteralPath $FilePath)) {
        Write-Host "SKIP: $Name executable not found: $FilePath" -ForegroundColor Yellow
        return
    }

    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id -NoNewline -Encoding ASCII
    Write-Host "STARTED: $Name" -ForegroundColor Green
    Write-Host "  PID: $($process.Id)"
    Write-Host "  stdout: $StdoutLog"
    Write-Host "  stderr: $StderrLog"
    Write-Host "  pid file: $PidFile"
}

function Test-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        [pscustomobject]@{
            Check = $Name
            Url = $Url
            Status = $response.StatusCode
            Result = 'ok'
        }
    }
    catch {
        $statusCode = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { '' }
        [pscustomobject]@{
            Check = $Name
            Url = $Url
            Status = $statusCode
            Result = $_.Exception.Message
        }
    }
}

function Enable-LocalPostgresUrlForGoServices {
    if (-not $env:DATABASE_URL) {
        $env:DATABASE_URL = "$defaultDatabaseUrl`?sslmode=disable"
        return
    }

    if ($env:DATABASE_URL -notmatch 'sslmode=') {
        if ($env:DATABASE_URL.Contains('?')) {
            $env:DATABASE_URL = "$($env:DATABASE_URL)&sslmode=disable"
        }
        else {
            $env:DATABASE_URL = "$($env:DATABASE_URL)?sslmode=disable"
        }
    }
}

function Start-OptionalGoServices {
    $engineDir = Join-Path $repoRootFull 'engine-go'
    Enable-LocalPostgresUrlForGoServices

    $services = @(
        @{ Name = 'Optical PathFinder'; Port = 50051; Exe = 'optical-service.exe'; LogPrefix = 'optical-service' },
        @{ Name = 'Batch Operations'; Port = 50052; Exe = 'batch-service.exe'; LogPrefix = 'batch-service' },
        @{ Name = 'Status Propagation'; Port = 50053; Exe = 'status-service.exe'; LogPrefix = 'status-service' },
        @{ Name = 'Port Summary'; Port = 50054; Exe = 'port-summary-service.exe'; LogPrefix = 'port-summary-service'; EnvPort = '50054' }
    )

    foreach ($service in $services) {
        $exePath = Join-Path $engineDir "bin\$($service.Exe)"

        if ($service.EnvPort) {
            $env:PORT = $service.EnvPort
        }

        try {
            Start-LoggedProcess -Name $service.Name `
                -Port $service.Port `
                -WorkingDirectory $engineDir `
                -FilePath $exePath `
                -ArgumentList @() `
                -StdoutLog (Join-Path $logsDir "$($service.LogPrefix).out.log") `
                -StderrLog (Join-Path $logsDir "$($service.LogPrefix).err.log") `
                -PidFile (Join-Path $logsDir "$($service.LogPrefix).pid")
        }
        catch {
            Write-Host "OPTIONAL FAILED: $($service.Name): $($_.Exception.Message)" -ForegroundColor Yellow
        }
        finally {
            if ($service.EnvPort) {
                Remove-Item Env:PORT -ErrorAction SilentlyContinue
            }
        }

        Write-Host ''
    }
}

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

Write-Host 'UNOC logged background start' -ForegroundColor Cyan
Write-Host "Repo root: $repoRootFull"
Write-Host "Logs: $logsDir"
Write-Host ''

Write-Host 'Starting PostgreSQL compose service' -ForegroundColor Cyan
Push-Location $repoRootFull
try {
    docker compose up -d postgres
}
finally {
    Pop-Location
}
Write-Host ''

if (-not $NoEngine) {
    $engineDir = Join-Path $repoRootFull 'engine-go'
    $engineExe = Join-Path $engineDir 'bin\traffic-engine.exe'
    Start-LoggedProcess -Name 'Go Traffic Engine' `
        -Port 8080 `
        -WorkingDirectory $engineDir `
        -FilePath $engineExe `
        -ArgumentList @() `
        -StdoutLog (Join-Path $logsDir 'traffic-engine.out.log') `
        -StderrLog (Join-Path $logsDir 'traffic-engine.err.log') `
        -PidFile (Join-Path $logsDir 'traffic-engine.pid')
    Write-Host ''
}
else {
    Write-Host 'SKIP: Go Traffic Engine disabled by -NoEngine.' -ForegroundColor Yellow
}

if ($IncludeOptionalGoServices) {
    Write-Host 'Starting optional Go/gRPC services' -ForegroundColor Cyan
    Start-OptionalGoServices
}
else {
    Write-Host 'SKIP: optional Go/gRPC services disabled. Use -IncludeOptionalGoServices to start them.' -ForegroundColor Yellow
    Write-Host ''
}

if (-not $NoBackend) {
    $python = @('.venv\Scripts\python.exe', '.venv-audit\Scripts\python.exe') |
        ForEach-Object { Join-Path $repoRootFull $_ } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1

    if (-not $python) {
        Write-Host 'SKIP: backend venv not found. Create .venv or .venv-audit first.' -ForegroundColor Yellow
    }
    else {
        if (-not $env:DATABASE_URL) { $env:DATABASE_URL = $defaultDatabaseUrl }
        if (-not $env:UNOC_DEV_FEATURES) { $env:UNOC_DEV_FEATURES = '1' }
        if (-not $env:UNOC_DISABLE_RELOAD) { $env:UNOC_DISABLE_RELOAD = '1' }
        if (-not $env:AUTO_ASSIGN_DEFAULT_HARDWARE) { $env:AUTO_ASSIGN_DEFAULT_HARDWARE = '1' }

        Start-LoggedProcess -Name 'FastAPI backend' `
            -Port 5001 `
            -WorkingDirectory $repoRootFull `
            -FilePath $python `
            -ArgumentList @('run.py') `
            -StdoutLog (Join-Path $logsDir 'backend.out.log') `
            -StderrLog (Join-Path $logsDir 'backend.err.log') `
            -PidFile (Join-Path $logsDir 'backend.pid')
        Write-Host ''
    }
}
else {
    Write-Host 'SKIP: backend disabled by -NoBackend.' -ForegroundColor Yellow
}

if (-not $NoFrontend) {
    $frontendDir = Join-Path $repoRootFull 'unoc-frontend-v2'
    $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if (-not $npx) { $npx = Get-Command npx -ErrorAction SilentlyContinue }

    if (-not $npx) {
        Write-Host 'SKIP: npx was not found on PATH.' -ForegroundColor Yellow
    }
    else {
        Start-LoggedProcess -Name 'Vue/Vite frontend' `
            -Port 5173 `
            -WorkingDirectory $frontendDir `
            -FilePath $npx.Source `
            -ArgumentList @('vite', '--host', '127.0.0.1', '--port', '5173', '--strictPort') `
            -StdoutLog (Join-Path $logsDir 'frontend.out.log') `
            -StderrLog (Join-Path $logsDir 'frontend.err.log') `
            -PidFile (Join-Path $logsDir 'frontend.pid')
        Write-Host ''
    }
}
else {
    Write-Host 'SKIP: frontend disabled by -NoFrontend.' -ForegroundColor Yellow
}

if (-not $SkipHealthCheck) {
    Start-Sleep -Seconds 2
    Write-Host 'HTTP checks' -ForegroundColor Cyan
    @(
        @{ Name = 'Traffic Engine health'; Url = 'http://127.0.0.1:8080/health' },
        @{ Name = 'Backend health'; Url = 'http://127.0.0.1:5001/api/health' },
        @{ Name = 'Frontend'; Url = 'http://127.0.0.1:5173' },
        @{ Name = 'Debug snapshot'; Url = 'http://127.0.0.1:5001/api/debug/full-snapshot' }
    ) | ForEach-Object { Test-HttpEndpoint -Name $_.Name -Url $_.Url } | Format-Table -AutoSize
}
else {
    Write-Host 'SKIP: health checks disabled by -SkipHealthCheck.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'URLs' -ForegroundColor Cyan
Write-Host '  frontend:       http://127.0.0.1:5173'
Write-Host '  backend:        http://127.0.0.1:5001'
Write-Host '  traffic engine: http://127.0.0.1:8080'