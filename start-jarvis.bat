@echo off
setlocal
cd /d "%~dp0"
if exist "backend\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("backend\.env") do if "%%A"=="JARVIS_API_TOKEN" set "JARVIS_API_TOKEN=%%B"
)
if not defined JARVIS_API_TOKEN (
  echo JARVIS Core token is missing. Create backend\.env from backend\.env.example and set JARVIS_API_TOKEN.
  pause
  exit /b 1
)
set "JARVIS_AGENT_API_URL=http://127.0.0.1:8767"
powershell -NoProfile -Command "try { $h=Invoke-RestMethod 'http://127.0.0.1:8767/health' -TimeoutSec 2; if ($h.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 start "JARVIS Core API" /min /D "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m jarvis.cli serve
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8765
python app.py
