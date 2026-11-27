$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8765"
$needsRestart = $true
try {
  $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2
  $needsRestart = !($health.agent_core -and $health.lm_studio)
} catch { $needsRestart = $true }
if ($needsRestart) { & (Join-Path $Project "restart-jarvis-server.ps1") }
& (Join-Path $Project "launch-jarvis-window.ps1")
