@echo off
REM Double-click this file. It always runs from its own folder, so it cannot
REM pick up an old copy sitting somewhere else.
cd /d "%~dp0"
echo Folder: %CD%
echo.
python -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail
python run.py %*
pause
goto :eof
:fail
echo.
echo Could not install dependencies. Is Python 3.10+ on your PATH?
pause
