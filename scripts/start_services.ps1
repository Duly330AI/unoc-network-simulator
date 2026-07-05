# UNOC Go Services - Startup Script
# Week 1 Day 4: Start all 3 Go microservices (Optical, Batch, Status)

Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host " Starting UNOC Go Services" -ForegroundColor Yellow
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""

# Check if binaries exist
$binPath = "$PSScriptRoot\..\engine-go\bin"
$services = @(
    @{Name="Optical Compute"; Exe="optical-service.exe"; Port=50051},
    @{Name="Batch Operations"; Exe="batch-service.exe"; Port=50052},
    @{Name="Status Propagation"; Exe="status-service.exe"; Port=50053}
)

$missing = @()
foreach ($svc in $services) {
    $path = Join-Path $binPath $svc.Exe
    if (-not (Test-Path $path)) {
        $missing += $svc.Exe
    }
}

if ($missing.Count -gt 0) {
    Write-Host "ERROR: Missing binaries:" -ForegroundColor Red
    foreach ($m in $missing) {
        Write-Host "  - $m" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Build them first:" -ForegroundColor Yellow
    Write-Host "  cd engine-go" -ForegroundColor Cyan
    Write-Host "  go build -o bin/optical-service.exe ./cmd/optical-service/" -ForegroundColor Cyan
    Write-Host "  go build -o bin/batch-service.exe ./cmd/batch-service/" -ForegroundColor Cyan
    Write-Host "  go build -o bin/status-service.exe ./cmd/status-service/" -ForegroundColor Cyan
    exit 1
}

# Check if ports are already in use
Write-Host "Checking ports..." -ForegroundColor Cyan
$portsInUse = @()
foreach ($svc in $services) {
    $connection = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue
    if ($connection) {
        $portsInUse += $svc.Port
        Write-Host "  Port $($svc.Port) ($($svc.Name)) - IN USE" -ForegroundColor Yellow
    } else {
        Write-Host "  Port $($svc.Port) ($($svc.Name)) - available" -ForegroundColor Green
    }
}

if ($portsInUse.Count -gt 0) {
    Write-Host ""
    Write-Host "WARNING: Some ports are already in use." -ForegroundColor Yellow
    Write-Host "Services on these ports will fail to start:" -ForegroundColor Yellow
    foreach ($port in $portsInUse) {
        Write-Host "  - Port $port" -ForegroundColor Red
    }
    Write-Host ""
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 0
    }
}

# Set environment variables (defaults - can be overridden)
if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "postgresql://unoc:unocpw@localhost:5432/unocdb"
}

Write-Host ""
Write-Host "Starting services..." -ForegroundColor Cyan
Write-Host ""

# Start each service in a new window
foreach ($svc in $services) {
    $exePath = Join-Path $binPath $svc.Exe
    Write-Host "Starting $($svc.Name) ($($svc.Exe)) on port $($svc.Port)..." -ForegroundColor Green
    
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$binPath'; `$env:DATABASE_URL='$env:DATABASE_URL'; .\$($svc.Exe)"
    ) -WindowStyle Normal
}

Write-Host ""
Write-Host "All services started!" -ForegroundColor Green
Write-Host ""
Write-Host "Service Endpoints:" -ForegroundColor Cyan
Write-Host "  - Optical Compute:    localhost:50051" -ForegroundColor White
Write-Host "  - Batch Operations:   localhost:50052" -ForegroundColor White
Write-Host "  - Status Propagation: localhost:50053" -ForegroundColor White
Write-Host ""
Write-Host "Logs are visible in separate PowerShell windows." -ForegroundColor Yellow
Write-Host "Press Ctrl+C in each window to stop a service." -ForegroundColor Yellow
Write-Host ""
Write-Host "Test health checks:" -ForegroundColor Cyan
Write-Host "  python tools/dev/test_grpc_integration.py" -ForegroundColor White
Write-Host ""
