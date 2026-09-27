# MediaGrab AI Launcher for PowerShell
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "          MediaGrab AI — Universal Media Downloader" -ForegroundColor Green
Write-Host "         Zero-Trust SSRF Protection & Isolated Sandbox" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[1/2] Verifying Python backend dependencies..." -ForegroundColor Yellow
python -m pip install -q -r backend/requirements.txt

Write-Host "[2/2] Starting MediaGrab AI full-stack service on http://localhost:8000 ..." -ForegroundColor Green
Write-Host "Open http://localhost:8000 in your browser to access MediaGrab AI." -ForegroundColor White
Write-Host "Press Ctrl+C to terminate the server." -ForegroundColor Gray
Write-Host ""

python backend/run_backend.py
