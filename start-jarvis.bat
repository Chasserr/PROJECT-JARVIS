@echo off
setlocal
cd /d "%~dp0"
rem Hand off to the same entry point the shortcut uses. open-jarvis.ps1 starts the
rem stack only when the API is not answering, then launch-jarvis-window.ps1 opens
rem the dashboard. Nothing here opens a browser, so the window can never point at
rem a server that is not listening yet, and an existing JARVIS window is replaced
rem instead of being left on a stale stylesheet.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-jarvis.ps1"
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo JARVIS did not start. See the messages above.
  pause
)
exit /b %RC%
