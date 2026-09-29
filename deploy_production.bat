@echo off
title MediaGrab AI - Production Deployment
echo ==========================================================
echo          MediaGrab AI - Production Deployment             
echo ==========================================================

set PATH=%PATH%;D:\ffmpeg\bin;C:\ffmpeg\bin;C:\Program Files\nodejs
set PYTHONPATH=backend
set ENVIRONMENT=production

echo.
echo [1/3] Building production frontend with Vite...
cd frontend
call npm run build
if %ERRORLEVEL% neq 0 (
    echo Frontend build failed!
    cd ..
    pause
    exit /b %ERRORLEVEL%
)
cd ..
echo Frontend build complete! Static assets placed in frontend/dist.

echo.
echo [2/3] Checking backend requirements...
python -c "import fastapi, uvicorn, yt_dlp; print('Backend core dependencies verified.')"

echo.
echo [3/3] Launching unified production server on http://localhost:8000...
echo Both UI and API are served together on port 8000!
echo Press Ctrl+C to terminate.
echo.

python backend/run_backend.py
pause
