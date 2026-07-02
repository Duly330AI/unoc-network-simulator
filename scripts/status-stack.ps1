# Read-only status for the local UNOC development stack.
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

function Test-WorkCopyMatch {
    param([string]$CommandLine)

    if (-not $CommandLine -or $CommandLine -eq '<unavailable>') {
        return 'unknown'
    }

    if ($CommandLine.IndexOf($repoRootFull, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return 'yes'
    }

    return 'no'
}

function Show-PortStatus {
    param(
        [string]$Name,
        [int]$Port
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue

    if (-not $listeners) {
        [pscustomobject]@{
            Service = $Name
            Port = $Port
            Listening = 'no'
            PID = ''
            ProcessName = ''
            WorkCopyMatch = ''
            CommandLine = ''
        }
        return
    }

    foreach ($listener in $listeners) {
        $details = Get-ProcessDetails -ProcessId $listener.OwningProcess
        [pscustomobject]@{
            Service = $Name
            Port = $Port
            Listening = 'yes'
            PID = $listener.OwningProcess
            ProcessName = $details.ProcessName
            WorkCopyMatch = Test-WorkCopyMatch -CommandLine $details.CommandLine
            CommandLine = $details.CommandLine
        }
    }
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

$ports = @(
    @{ Name = 'PostgreSQL'; Port = 5432 },
    @{ Name = 'Go Traffic Engine'; Port = 8080 },
    @{ Name = 'Optical PathFinder'; Port = 50051 },
    @{ Name = 'Batch Operations'; Port = 50052 },
    @{ Name = 'Status Propagation'; Port = 50053 },
    @{ Name = 'Port Summary'; Port = 50054 },
    @{ Name = 'FastAPI backend'; Port = 5001 },
    @{ Name = 'Vue/Vite frontend'; Port = 5173 }
)

$checks = @(
    @{ Name = 'Traffic Engine health'; Url = 'http://127.0.0.1:8080/health' },
    @{ Name = 'Backend health'; Url = 'http://127.0.0.1:5001/api/health' },
    @{ Name = 'Frontend'; Url = 'http://127.0.0.1:5173' },
    @{ Name = 'Debug snapshot'; Url = 'http://127.0.0.1:5001/api/debug/full-snapshot' }
)

Write-Host "UNOC stack status" -ForegroundColor Cyan
Write-Host "Repo root: $repoRootFull"
Write-Host ''

Write-Host 'Ports' -ForegroundColor Cyan
$ports | ForEach-Object { Show-PortStatus -Name $_.Name -Port $_.Port } | Format-List

Write-Host 'HTTP checks' -ForegroundColor Cyan
$checks | ForEach-Object { Test-HttpEndpoint -Name $_.Name -Url $_.Url } | Format-Table -AutoSize