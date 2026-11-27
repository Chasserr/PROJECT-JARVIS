$matches=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' }
foreach($p in $matches){ Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
"Stopped Windows wake listener processes: $($matches.Count)"
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' } | Measure-Object | ForEach-Object { "Remaining listeners: $($_.Count)" }
