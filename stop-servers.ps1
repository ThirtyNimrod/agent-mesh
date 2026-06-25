# stop-servers.ps1
# Stops all agent-mesh MCP servers tracked in .server-pids.
# Falls back to killing by port (8001/8002/8003) if the PID file is missing.
#
# Usage:
#   .\stop-servers.ps1

$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile   = Join-Path $scriptDir ".server-pids"

$ports = @(8001, 8002, 8003)

Write-Host ""
Write-Host "Stopping agent-mesh servers..." -ForegroundColor Cyan
Write-Host ""

$stoppedAny = $false

# stop via PID file

if (Test-Path $pidFile) {
    $pidMap = Get-Content $pidFile | ConvertFrom-Json

    foreach ($entry in $pidMap.PSObject.Properties) {
        $name = $entry.Name
        $p    = [int]$entry.Value
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Write-Host "  Stopped $name (PID $p)" -ForegroundColor Green
            $stoppedAny = $true
        } else {
            Write-Host "  $name (PID $p) was not running" -ForegroundColor Gray
        }
    }

    Remove-Item $pidFile -Force
} else {
    Write-Host "  .server-pids not found - falling back to port scan" -ForegroundColor Gray
}

# fallback: kill anything still holding the known ports

foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($c in $conn) {
            $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Write-Host "  Killed process on port $port (PID $($proc.Id), $($proc.Name))" -ForegroundColor Yellow
                $stoppedAny = $true
            }
        }
    }
}

Write-Host ""
if ($stoppedAny) {
    Write-Host "Done." -ForegroundColor Cyan
} else {
    Write-Host "No running server processes were found." -ForegroundColor Gray
}
Write-Host ""
