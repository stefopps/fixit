@echo off
setlocal EnableExtensions
title FixIt
REM One instance + Administrator: fix global hotkeys and avoid duplicate panels.

cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo FixIt needs Administrator for hotkeys keyboard hook.
  echo Requesting UAC...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0.' -Verb RunAs"
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIXIT_ONCE.ps1"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo Done. FixIt should be open — you can minimize this window.
timeout /t 4 >nul
exit /b 0
