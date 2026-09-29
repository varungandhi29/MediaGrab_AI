@echo off
title MediaGrab AI - Public Live Deployment
echo ==========================================================
echo        MediaGrab AI - Public Live Deployment Launcher     
echo ==========================================================

set PATH=%PATH%;%~dp0;D:\ffmpeg\bin;C:\ffmpeg\bin;C:\Program Files\nodejs
set PYTHONPATH=backend
set ENVIRONMENT=production

echo.
echo [1/3] Building frontend assets...
cd frontend
call npm run build
cd ..

echo.
echo [2/3] Launching background production server on port 8000...
start /b python backend\run_backend.py > nul 2>&1
timeout /t 3 /nobreak > nul

echo.
echo [3/3] Launching live public HTTPS URL via Cloudflare Tunnel...
echo Anyone in the world can access your website through this public link!
echo.
cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate
pause
