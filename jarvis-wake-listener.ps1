$ErrorActionPreference = "Stop"
$Project = "C:\Users\Mesha\Desktop\PROJECT-JARVIS"
$Url = "http://127.0.0.1:8765"
$Log = Join-Path $Project "jarvis-wake.log"
function Log($m) { Add-Content -Path $Log -Value ("[{0}] {1}" -f (Get-Date -Format s),$m) }
$recognizer = $null
try {
  Add-Type -AssemblyName System.Speech
  $culture = [Globalization.CultureInfo]::GetCultureInfo("en-US")
  $recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($culture)
  $phrases = @("open jarvis","hey jarvis","okay jarvis","ok jarvis","wake up jarvis","wake up","jarvis")
  $choices = [System.Speech.Recognition.Choices]::new()
  foreach ($phrase in $phrases) { [void]$choices.Add($phrase) }
  $builder = [System.Speech.Recognition.GrammarBuilder]::new()
  $builder.Culture = $culture
  $builder.Append($choices)
  $recognizer.LoadGrammar([System.Speech.Recognition.Grammar]::new($builder))
  $recognizer.SetInputToDefaultAudioDevice()
  Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognized -SourceIdentifier JarvisWake | Out-Null
  $recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
  Log "Wake listener started. Phrases: $($phrases -join ', ')."
  $lastLaunch = [datetime]::MinValue
  while ($true) {
    $event = Wait-Event -SourceIdentifier JarvisWake -Timeout 1
    if (!$event) { continue }
    $phrase = $event.SourceEventArgs.Result.Text
    $confidence = [math]::Round($event.SourceEventArgs.Result.Confidence,2)
    Remove-Event -EventIdentifier $event.EventIdentifier
    if ($confidence -lt 0.35) { Log "Ignored low-confidence phrase '$phrase' ($confidence)."; continue }
    if (((Get-Date)-$lastLaunch).TotalSeconds -lt 2) { continue }
    $lastLaunch = Get-Date
    try { Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2 | Out-Null }
    catch { Start-Process -FilePath "C:\Python315\python.exe" -ArgumentList "app.py" -WorkingDirectory $Project -WindowStyle Hidden; Start-Sleep -Seconds 2 }
    & (Join-Path $Project "launch-jarvis-window.ps1")
    Log "Recognized '$phrase' (confidence $confidence); focused or opened the single JARVIS window."
  }
} catch {
  Log ("Listener error: " + $_.Exception.Message)
  throw
} finally {
  if ($recognizer) { $recognizer.Dispose() }
  Unregister-Event -SourceIdentifier JarvisWake -ErrorAction SilentlyContinue
}

