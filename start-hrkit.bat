@echo off
REM hrkit launcher — starts the web UI on http://127.0.0.1:8765/
cd /d "%~dp0"
python -m hrkit serve
pause
