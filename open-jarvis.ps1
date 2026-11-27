$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8765"
$needsRestart = $true
try {
  # The first health request probes the model backends and can take a couple of
  # seconds; a 2s timeout made a healthy stack look dead and forced a restart.
  $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 10
  # /api/health does not report every field a given provider uses, so judge by
  # what it does return: the app answered and a model backend is available.
  # LM Studio is optional here; OpenJarvis is the default provider.
  $needsRestart = !($health.app -eq 'online' -and ($health.openjarvis -or $health.lm_studio))
} catch { $needsRestart = $true }
if ($needsRestart) { & (Join-Path $Project "restart-jarvis-server.ps1") }
& (Join-Path $Project "launch-jarvis-window.ps1")
