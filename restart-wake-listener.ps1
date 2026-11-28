$Project = $PSScriptRoot
$Script = Join-Path $Project 'jarvis-wake-listener.ps1'
$Log = Join-Path $Project 'jarvis-wake.log'

if (-not (Test-Path $Script)) { throw "Wake listener script not found at $Script" }

$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' }
foreach ($x in $p) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`"" -WindowStyle Hidden
Start-Sleep -Seconds 2

$running = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' }
if (-not $running) { Write-Error "Wake listener did not stay running. Check $Log" }
if (Test-Path $Log) { Get-Content $Log -Tail 5 } else { Write-Warning "No wake log yet at $Log" }
