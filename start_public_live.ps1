<#
.SYNOPSIS
    Builds and starts MediaGrab AI in production mode and generates a public live HTTPS URL via Cloudflare.
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       MediaGrab AI - Public Live Deployment Launcher     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Set environment
$env:PATH += ";$PSScriptRoot;D:\ffmpeg\bin;C:\ffmpeg\bin;C:\Program Files\nodejs"
$env:PYTHONPATH = "backend"
$env:ENVIRONMENT = "production"

Write-Host "`n[1/3] Building frontend assets..." -ForegroundColor Yellow
Push-Location frontend
npm run build
Pop-Location

Write-Host "`n[2/3] Launching background production server on port 8000..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    param($root)
    $env:PATH += ";$root;D:\ffmpeg\bin;C:\ffmpeg\bin;C:\Program Files\nodejs"
    $env:PYTHONPATH = "$root\backend"
    $env:ENVIRONMENT = "production"
    Set-Location $root
    python backend\run_backend.py
} -ArgumentList $PSScriptRoot

Start-Sleep -Seconds 3

Write-Host "`n[3/3] Creating live public HTTPS URL via Cloudflare Tunnel..." -ForegroundColor Green
Write-Host "Anyone in the world can access your website through this public link!" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the live server.`n" -ForegroundColor DarkGray

.\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate
