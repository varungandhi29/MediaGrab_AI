@echo off
title MediaGrab AI Launcher
echo ============================================================
echo           MediaGrab AI — Universal Media Downloader
echo          Zero-Trust SSRF Protection & Isolated Sandbox
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/2] Checking backend requirements...
python -m pip install -q -r backend/requirements.txt

echo [2/2] Launching MediaGrab AI server on http://localhost:8000 ...
echo Press Ctrl+C to terminate the server.
echo.

python backend/run_backend.py
pause
