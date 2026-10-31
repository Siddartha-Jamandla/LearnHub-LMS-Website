@echo off
REM LearnHub LMS - one-command local dev setup (Windows)
cd /d "%~dp0"

echo ==^> Seeding database...
py -3 backend\seed.py
if errorlevel 1 ( python backend\seed.py )

echo ==^> Starting LearnHub backend on http://localhost:8000
py -3 backend\app.py
if errorlevel 1 ( python backend\app.py )
