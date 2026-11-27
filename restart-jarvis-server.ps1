$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Project "backend"
$EnvFile = Join-Path $Backend ".env"
if (!(Test-Path $EnvFile)) { throw "JARVIS backend/.env is missing." }
$TokenLine = Get-Content $EnvFile | Where-Object { $_ -match '^JARVIS_API_TOKEN=.+' } | Select-Object -First 1
if (!$TokenLine) { throw "JARVIS_API_TOKEN is missing from backend/.env." }
$env:JARVIS_API_TOKEN = ($TokenLine -split '=',2)[1].Trim()
$env:JARVIS_AGENT_API_URL = "http://127.0.0.1:8767"
$env:JARVIS_OPENJARVIS_API_URL = "http://127.0.0.1:8000"
$env:JARVIS_OPENJARVIS_MODEL = "qwen3.5:4b"
$env:JARVIS_PORT = "8765"
$OpenJarvisRoot = Join-Path $env:LOCALAPPDATA "OpenJarvis\\src"
$OpenJarvisPython = Join-Path $OpenJarvisRoot ".venv\\Scripts\\python.exe"
if (!(Test-Path $OpenJarvisPython)) { throw "OpenJarvis Python environment is missing: $OpenJarvisPython" }
try {
  $oj = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 2
  if ($oj.status -ne "ok") { throw "OpenJarvis health check failed." }
} catch {
  Start-Process -FilePath $OpenJarvisPython -ArgumentList @("-m","openjarvis.cli","serve","--host","127.0.0.1","--port","8000","--engine","ollama","--model","qwen3.5:4b","--agent","orchestrator") -WorkingDirectory $OpenJarvisRoot -WindowStyle Hidden
  $ready = $false
  for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try { $oj = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 2; if ($oj.status -eq "ok") { $ready = $true; break } } catch {}
  }
  if (!$ready) { throw "OpenJarvis did not become healthy on 127.0.0.1:8000." }
}
$env:BRAVE_SEARCH_API_KEY = [Environment]::GetEnvironmentVariable('BRAVE_SEARCH_API_KEY','User')
$env:JARVIS_BRAVE_API_KEY = [Environment]::GetEnvironmentVariable('JARVIS_BRAVE_API_KEY','User')
if (!$env:JARVIS_BRAVE_API_KEY) { $env:JARVIS_BRAVE_API_KEY = $env:BRAVE_SEARCH_API_KEY }
$env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY','User')
try {
  $core = Invoke-RestMethod 'http://127.0.0.1:8767/health' -TimeoutSec 2
  if ($core.status -ne 'ok') { throw "JARVIS Core is unhealthy." }
} catch {
  Start-Process -FilePath (Join-Path $Backend ".venv\Scripts\python.exe") -ArgumentList '-m jarvis.cli serve' -WorkingDirectory $Backend -WindowStyle Hidden
  Start-Sleep -Seconds 4
  $core = Invoke-RestMethod 'http://127.0.0.1:8767/health' -TimeoutSec 5
}
$listener=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if($listener){
  $existing=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
  if($existing.CommandLine -notlike '*app.py*' -or $existing.ExecutablePath -ne 'C:\Python315\python.exe') { throw "Port 8765 is occupied by an unexpected process; refusing to stop it." }
  Stop-Process -Id $listener.OwningProcess -Force
  Start-Sleep -Seconds 1
}
Start-Process -FilePath 'C:\Python315\python.exe' -ArgumentList 'app.py' -WorkingDirectory $Project -WindowStyle Hidden
Start-Sleep -Seconds 2
$h=Invoke-RestMethod 'http://127.0.0.1:8765/api/health'
"Health: $($h.app), core online: $($h.lm_studio), provider: $($h.provider), model: $($h.model)"
$a=Invoke-RestMethod 'http://127.0.0.1:8765/api/apps'
"Installed app catalogue count: $($a.apps.Count)"
"CapCut listed: " + [bool]($a.apps | Where-Object {$_.name -eq 'CapCut'})
