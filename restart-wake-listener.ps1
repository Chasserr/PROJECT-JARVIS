$Project = $PSScriptRoot
$Script = Join-Path $Project 'jarvis-wake-listener.ps1'
$Log = Join-Path $Project 'jarvis-wake.log'

if (-not (Test-Path $Script)) { throw "Wake listener script not found at $Script" }

function Get-WakeListeners {
  # Exclude this script's own process: its command line also names the listener.
  Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' }
}

foreach ($x in Get-WakeListeners) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }

# The named mutex is only released once the old process is gone; starting the new
# listener too early makes it exit on the mutex. Wait for a clean handover.
for ($i = 0; $i -lt 10; $i++) {
  if (-not (Get-WakeListeners)) { break }
  Start-Sleep -Milliseconds 500
}
if (Get-WakeListeners) { throw "The previous wake listener did not exit; refusing to start a second one." }

Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`"" -WindowStyle Hidden
Start-Sleep -Seconds 2

$running = @(Get-WakeListeners)
if ($running.Count -eq 0) { Write-Error "Wake listener did not stay running. Check $Log" }
elseif ($running.Count -gt 1) { Write-Error "Expected one wake listener, found $($running.Count)." }
else { Write-Host "Wake listener running (1 instance)." }

if (Test-Path $Log) { Get-Content $Log -Tail 5 } else { Write-Warning "No wake log yet at $Log" }
