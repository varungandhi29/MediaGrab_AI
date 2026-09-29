<#
.SYNOPSIS
    Builds frontend and starts MediaGrab AI in unified production mode on port 8000.
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         MediaGrab AI - Production Deployment             " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Set environment paths
$env:PATH += ";D:\ffmpeg\bin;C:\ffmpeg\bin;C:\Program Files\nodejs"
$env:PYTHONPATH = "backend"
$env:ENVIRONMENT = "production"

Write-Host "`n[1/3] Building production frontend with Vite..." -ForegroundColor Yellow
Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Frontend build failed!" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "Frontend build complete! Static assets placed in frontend/dist." -ForegroundColor Green

Write-Host "`n[2/3] Checking backend requirements..." -ForegroundColor Yellow
python -c "import fastapi, uvicorn, yt_dlp; print('Backend core dependencies verified.')"

Write-Host "`n[3/3] Launching unified production server on http://localhost:8000..." -ForegroundColor Green
Write-Host "Press Ctrl+C to terminate.`n" -ForegroundColor DarkGray

python backend/run_backend.py
