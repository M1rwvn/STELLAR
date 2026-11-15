# Plan B: run the whole backend on this laptop with no Docker and no internet
# (internet is only needed the first time, to install the libraries).
# Uses SQLite (stellar.db). From the repo root:
#   scripts\run_local.bat            # API  -> http://127.0.0.1:8000/docs
#   scripts\run_local.bat -Mock      # Mock -> http://127.0.0.1:8001/docs
#   scripts\run_local.bat -Reset     # start again with an empty database
param([switch]$Mock, [switch]$Reset)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Find Python 3.11+ (the "py" launcher first, then "python")
$py = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    $exe = $candidate[0]
    $pyArgs = @($candidate | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $ver = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -and [version]$ver -ge [version]"3.11") {
            $py = $candidate
            break
        }
    }
}
if (-not $py) {
    Write-Host "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the virtual environment (.venv) ..."
    $pyExe = $py[0]
    $pyRest = @($py | Select-Object -Skip 1)
    & $pyExe @pyRest -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create .venv" -ForegroundColor Red; exit 1 }
}

Write-Host "Checking libraries (first run downloads them) ..."
.\.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the libraries failed. Check your internet connection and run this again." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if ($Reset -and (Test-Path "stellar.db")) { Remove-Item "stellar.db"; Write-Host "Database reset." }

if ($Mock) {
    Write-Host "Mock API -> http://127.0.0.1:8001/docs   (Ctrl+C to stop)" -ForegroundColor Green
    .\.venv\Scripts\python -m uvicorn app.mock_api:app --host 0.0.0.0 --port 8001
} else {
    Write-Host "API -> http://127.0.0.1:8000/docs   (Ctrl+C to stop)" -ForegroundColor Green
    .\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
}
