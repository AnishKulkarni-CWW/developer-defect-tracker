@echo off
REM QA Report Studio - Windows launcher
title QA Report Studio
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on this PC.
  echo Install Python 3.10 or newer from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv\" (
  echo Creating a private environment. This happens once and takes a minute...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

echo.
echo Starting QA Report Studio. Your browser will open shortly.
echo Close this window to stop the app.
echo.
streamlit run app.py
pause
