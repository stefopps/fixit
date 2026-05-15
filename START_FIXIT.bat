@echo off
REM Closes old FixIt copies, starts exactly one (as Admin)
echo Closing any old FixIt instances...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*fixit*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul
echo Starting FixIt...
cd /d "%~dp0"
powershell -Command "Start-Process python -ArgumentList 'main.py' -WorkingDirectory '%cd%' -Verb RunAs"
