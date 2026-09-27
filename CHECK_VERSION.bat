@echo off
REM Tells you which build is in THIS folder, without starting the server.
cd /d "%~dp0"
echo Folder: %CD%
echo.
findstr /C:"VERSION = " run.py
findstr /C:"check-ai" run.py >nul 2>&1 && echo   --check-ai : present  (v2, correct) || echo   --check-ai : MISSING  (old copy - extract the new zip here)
echo.
pause
