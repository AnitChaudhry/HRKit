@echo off
REM hrkit launcher — runs `hrkit serve` in this workspace.
REM After it prints "Serving on ...", your default browser will open
REM automatically to http://127.0.0.1:8765/  (that URL is THIS machine —
REM it works only while this window stays open; closing this window
REM stops the app).
cd /d "%~dp0"
echo.
echo Starting HR-Kit on your machine. The browser will open shortly.
echo Keep this window open while you use the app. Close it to stop.
echo.
python -m hrkit serve
pause
