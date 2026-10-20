@echo off
cd /d "%~dp0"
python -m venv .runtime
if errorlevel 1 goto fail
.runtime\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers"
.runtime\Scripts\python.exe -m playwright install firefox
if errorlevel 1 goto fail
call start.cmd
exit /b 0
:fail
echo Installation failed. Check Python and network connection.
pause
exit /b 1
