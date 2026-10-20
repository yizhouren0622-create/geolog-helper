@echo off
cd /d "%~dp0"
if not exist ".runtime\Scripts\pythonw.exe" (
  echo Runtime missing. Please run install.cmd first.
  pause
  exit /b 1
)
start "" ".runtime\Scripts\pythonw.exe" "launch.py"
