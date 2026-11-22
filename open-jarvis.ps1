$Project = "C:\Users\Mesha\Desktop\PROJECT-JARVIS"
$Url = "http://127.0.0.1:8765"
try {
  Invoke-WebRequest -Uri "$Url/api/health" -TimeoutSec 2 -UseBasicParsing | Out-Null
} catch {
  Start-Process -FilePath "C:\Python315\python.exe" -ArgumentList "app.py" -WorkingDirectory $Project -WindowStyle Hidden
}
Start-Sleep -Seconds 2
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (!(Test-Path $Edge)) { $Edge = "C:\Program Files\Google\Chrome\Application\chrome.exe" }
Start-Process -FilePath $Edge -ArgumentList "--app=$Url"