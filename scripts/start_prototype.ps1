# STELLAR prototype - one-click demo.
#   1) starts the backend (fresh database) in its own window
#   2) waits until it answers (first run: installs the libraries, needs internet once)
#   3) opens the Ground Control dashboard in the browser
#   4) streams the three astronauts' data live in a second window
# Usage: double-click START_PROTOTYPE.bat in the project folder
param([int]$StartDay = 45, [double]$Interval = 0.3)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$url = "http://127.0.0.1:8000"
$q = $root.Replace("'", "''")   # safe inside single quotes even if the path has an apostrophe

function Test-Api {
    try { Invoke-WebRequest -UseBasicParsing "$url/health" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

Write-Host ""
Write-Host "  STELLAR prototype" -ForegroundColor Cyan
Write-Host "  -----------------------"

if (Test-Api) {
    Write-Host "  Something is already running on port 8000. Close the old server window first, then run this again." -ForegroundColor Yellow
    Read-Host "  Press Enter to close"
    exit 1
}

Write-Host "  [1/4] Starting the server (window 'STELLAR - Server') ..."
Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
    "-Command", "`$host.UI.RawUI.WindowTitle = 'STELLAR - Server'; & '$q\scripts\run_local.ps1' -Reset"

Write-Host "  [2/4] Waiting for the server (first run downloads the libraries: a few minutes) ..."
$ok = $false
for ($i = 0; $i -lt 900; $i++) {
    if (Test-Api) { $ok = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ok) {
    Write-Host "  The server did not start. Look at the 'STELLAR - Server' window for the reason." -ForegroundColor Red
    Read-Host "  Press Enter to close"
    exit 1
}
$health = (Invoke-WebRequest -UseBasicParsing "$url/health").Content
Write-Host "        server is up: $health" -ForegroundColor Green

Write-Host "  [3/4] Opening the Ground Control dashboard ..."
Start-Process "$url/dashboard"

Write-Host "  [4/4] Streaming live data (window 'STELLAR - Live data') ..."
Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
    "-Command", "`$host.UI.RawUI.WindowTitle = 'STELLAR - Live data'; Set-Location '$q'; & '.\.venv\Scripts\python.exe' scripts\replay.py --start-day $StartDay --every-hours 6 --interval $Interval"

Write-Host ""
Write-Host "  Ready." -ForegroundColor Green
Write-Host "  Dashboard : $url/dashboard"
Write-Host "  API docs  : $url/docs   (login: ground / astro123)"
Write-Host "  To stop   : close the two windows 'STELLAR - Server' and 'STELLAR - Live data'."
Write-Host ""
Start-Sleep -Seconds 8
