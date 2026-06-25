# start-servers.ps1
# Starts the three agent-mesh MCP servers as background processes.
# PIDs are saved to .server-pids so stop-servers.ps1 can shut them down.
#
# Usage:
#   .\start-servers.ps1            # hidden windows (default)
#   .\start-servers.ps1 -Visible   # minimized windows (easier to debug)

param(
    [switch]$Visible
)

$ErrorActionPreference = "Stop"
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$python     = Join-Path $scriptDir ".venv\Scripts\python.exe"
$pidFile    = Join-Path $scriptDir ".server-pids"

# pre-flight checks

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found at '$python'. Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile | ConvertFrom-Json
    $anyAlive = $false
    foreach ($entry in $existing.PSObject.Properties) {
        try { Get-Process -Id ([int]$entry.Value) -ErrorAction Stop | Out-Null; $anyAlive = $true } catch {}
    }
    if ($anyAlive) {
        Write-Host "One or more servers are already running. Run stop-servers.ps1 first." -ForegroundColor Yellow
        exit 1
    }
    Remove-Item $pidFile -Force
}

# server definitions

$servers = @(
    [PSCustomObject]@{ Name = "memory-server";       Module = "servers.memory_server";       Port = 8001 },
    [PSCustomObject]@{ Name = "file-bridge-server";  Module = "servers.file_bridge_server";  Port = 8002 },
    [PSCustomObject]@{ Name = "prompt-audit-server"; Module = "servers.prompt_audit_server"; Port = 8003 }
)

$windowStyle = if ($Visible) { "Minimized" } else { "Hidden" }

# launch

Write-Host ""
Write-Host "Starting agent-mesh servers..." -ForegroundColor Cyan
Write-Host ""

$pidMap = @{}

foreach ($s in $servers) {
    $proc = Start-Process `
        -FilePath         $python `
        -ArgumentList     "-m $($s.Module)" `
        -WorkingDirectory $scriptDir `
        -WindowStyle      $windowStyle `
        -PassThru

    $pidMap[$s.Name] = $proc.Id
    Write-Host ("  {0,-25} PID {1,-7}  http://localhost:{2}/mcp" -f $s.Name, $proc.Id, $s.Port) -ForegroundColor Green
}

$pidMap | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

# brief startup wait then alive-check

Write-Host ""
Write-Host "Waiting 3s for processes to settle..." -ForegroundColor Gray
Start-Sleep -Seconds 3

$allAlive = $true
foreach ($s in $servers) {
    $p = [int]$pidMap[$s.Name]
    try {
        Get-Process -Id $p -ErrorAction Stop | Out-Null
        Write-Host "  $($s.Name) is running (PID $p)" -ForegroundColor Green
    } catch {
        Write-Host "  $($s.Name) exited unexpectedly - check logs directory" -ForegroundColor Red
        $allAlive = $false
    }
}

Write-Host ""
if ($allAlive) {
    Write-Host "All servers are up." -ForegroundColor Cyan
} else {
    Write-Host "One or more servers failed to start. Check the logs directory for details." -ForegroundColor Yellow
}

Write-Host "Logs:          logs\"
Write-Host "Stop servers:  .\stop-servers.ps1"
Write-Host ""
