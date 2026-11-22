$env:BRAVE_SEARCH_API_KEY = [Environment]::GetEnvironmentVariable('BRAVE_SEARCH_API_KEY','User')
$env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY','User')
$listener=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if($listener){ Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }
Start-Process -FilePath 'C:\Python315\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Mesha\Desktop\PROJECT-JARVIS' -WindowStyle Hidden
Start-Sleep -Seconds 2
$h=Invoke-RestMethod 'http://127.0.0.1:8765/api/health'
"Health: $($h.app), model online: $($h.lm_studio)"
$a=Invoke-RestMethod 'http://127.0.0.1:8765/api/apps'
"Installed app catalogue count: $($a.apps.Count)"
"CapCut listed: "+[bool]($a.apps | Where-Object {$_.name -eq 'CapCut'})
