$ErrorActionPreference = "Stop"
$Project = "E:\PROJECT-JARVIS"
$Backend = Join-Path $Project "backend"
$PythonRoot = "C:\Python315\python.exe"
$PythonCore = "C:\Users\Mesha\AppData\Local\Programs\Python\Python313\python.exe"

$env:BRAVE_SEARCH_API_KEY = [Environment]::GetEnvironmentVariable("BRAVE_SEARCH_API_KEY", "User")
$env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable("ELEVENLABS_API_KEY", "User")

foreach ($port in @(8765, 8766)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

Start-Process -FilePath $PythonCore -ArgumentList @(
    "-m", "uvicorn", "jarvis.api:app", "--app-dir", "src",
    "--host", "127.0.0.1", "--port", "8766"
) -WorkingDirectory $Backend -WindowStyle Hidden
Start-Process -FilePath $PythonRoot -ArgumentList "app.py" -WorkingDirectory $Project -WindowStyle Hidden
Start-Sleep -Seconds 3

$health = Invoke-RestMethod "http://127.0.0.1:8765/api/health" -TimeoutSec 5
$core = Invoke-RestMethod "http://127.0.0.1:8766/api/v1/security/status" -TimeoutSec 5
"JARVIS: $($health.app); model available: $($health.llm_available)"
"Security scanner available: $($core.available); latest report: $($core.latest_report_available)"
