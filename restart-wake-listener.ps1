$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^powershell' -and $_.CommandLine -like '*jarvis-wake-listener.ps1*' }
foreach($x in $p){ Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Mesha\Desktop\PROJECT-JARVIS\jarvis-wake-listener.ps1"' -WindowStyle Hidden
Start-Sleep -Seconds 2
Get-Content 'C:\Users\Mesha\Desktop\PROJECT-JARVIS\jarvis-wake.log' -Tail 5