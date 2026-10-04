# Start the vehicle and agent services for development (Windows PowerShell).
# Usage: .\scripts\dev.ps1 [-Profile replay]
param([string]$Profile = "replay")
Set-Location (Join-Path $PSScriptRoot "..")
$vehicle = Start-Process python -ArgumentList "-m", "mavmind_vehicle", "--profile", $Profile -PassThru -NoNewWindow
try {
    Start-Sleep -Seconds 2
    python -m mavmind_agent
} finally {
    Stop-Process -Id $vehicle.Id -ErrorAction SilentlyContinue
}
