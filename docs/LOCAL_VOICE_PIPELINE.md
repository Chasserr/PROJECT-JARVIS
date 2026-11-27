# JARVIS Local Voice Pipeline — 2026-11-25

## Implemented
- Kokoro local text-to-speech is connected to the desktop application's authenticated-by-origin local voice endpoint.
- faster-whisper local transcription endpoint accepts bounded multipart audio uploads (25 MB maximum).
- The desktop orb now records microphone audio with MediaRecorder and submits it to the local Whisper endpoint.
- The wake phrase listener remains available; after a wake-only phrase, JARVIS starts a short local audio capture for command transcription.
- The capture automatically stops after seven seconds or when the user taps the orb again.
- Browser speech recognition is retained only as the wake-phrase detector; command audio is transcribed by local faster-whisper.

## Verification
- Python syntax check passed.
- JavaScript syntax check passed.
- JARVIS backend test suite: 67 passed.
- Live HTTP multipart smoke test: generated a WAV with Kokoro, uploaded it to /api/voice/transcribe, and received a correct faster-whisper transcript.
- Live /api/voice/speak endpoint returns a WAV file.
- Temporary audio files are removed after processing.

## Notes
- Microphone capture requires the user to grant microphone permission in Edge/Chrome.
- Browser wake-word detection still depends on the browser SpeechRecognition implementation; the captured command itself uses local Whisper.
- Processing is CPU-based today. Do not assume CUDA acceleration.
- Keep the server on loopback and preserve the existing Origin and host checks.
