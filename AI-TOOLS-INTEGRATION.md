# JARVIS Voice Integration

JARVIS desktop voice output now uses the shared local Kokoro engine at `C:\Users\Mesha\AI-Tools\VoiceStack`.

- `GET /api/voice/status` reports Kokoro local availability.
- `POST /api/voice/speak` accepts text and an allow-listed Kokoro voice, then returns WAV audio.
- Output is generated to a unique temporary file and removed after the response.
- The existing browser speech recognizer detects the wake phrase; microphone command audio is recorded by MediaRecorder and transcribed by the local faster-whisper endpoint.
- The microphone orb starts/stops a bounded seven-second local recording. The wake phrase starts capture automatically.

Keep JARVIS bound to loopback. Audio generation is local; no cloud voice provider is called.
