$ErrorActionPreference = "Stop"
$Project = "E:\PROJECT-JARVIS"
$Backend = Join-Path $Project "backend"
$Url = "http://127.0.0.1:8765"
$CoreUrl = "http://127.0.0.1:8766/api/v1/health"
$PythonRoot = "C:\Python315\python.exe"
$PythonCore = "C:\Users\Mesha\AppData\Local\Programs\Python\Python313\python.exe"

if (!(Test-Path $Project)) { throw "JARVIS project folder not found: $Project" }

try {
    Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath $PythonRoot -ArgumentList "app.py" -WorkingDirectory $Project -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

try {
    Invoke-RestMethod -Uri $CoreUrl -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath $PythonCore -ArgumentList @(
        "-m", "uvicorn", "jarvis.api:app", "--app-dir", "src",
        "--host", "127.0.0.1", "--port", "8766"
    ) -WorkingDirectory $Backend -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

Invoke-RestMethod -Uri "$Url/api/security/status" -TimeoutSec 5 | Out-Null
& (Join-Path $Project "launch-jarvis-window.ps1")
