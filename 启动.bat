@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>&1 || (
  echo [FRESH] pythonw not found in PATH.
  echo Install Python 3.11+ and enable "Add python.exe to PATH", or run: pyw main.py
  pause
  exit /b 1
)
start "" pythonw main.py
exit
