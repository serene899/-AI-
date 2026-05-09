@echo off
REM Crypto Sim - Windows one-click launcher
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo [ERR] Python not found. Please install Python 3.10+ and add to PATH.
  pause
  exit /b 1
)
python run.py
pause
