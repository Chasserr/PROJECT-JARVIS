# JARVIS Voice Engine

## Runtime components

- Wake word: openWakeWord, using the `hey_jarvis` / "Hey Jarvis" pretrained model.
- Speech recognition: faster-whisper, CPU/int8, multilingual model (default `base`).
- Speech synthesis: Piper `en_US-amy-medium` local female voice, streamed as generated audio chunks.
- Optional cloud synthesis: ElevenLabs streaming endpoint. If the selected library voice is not permitted by the account plan or the request fails, JARVIS falls back to Piper.
- Input: the configured Fifine microphone only.
- Output: the configured Echo Dot only.

## Install

From `backend`:

```powershell
uv sync --extra dev --extra voice
```

The Piper Amy model is stored under `data/voices` and is not committed to Git. The openWakeWord and Whisper models are downloaded into their normal local model caches on first use.

## Wake listener controls

The microphone is not opened when the API starts. Wake listening is opt-in and can be controlled locally:

- `GET /api/v1/voice/wake/status`
- `POST /api/v1/voice/wake/start`
- `POST /api/v1/voice/wake/stop`

Example start request:

```json
{
  "threshold": 0.55,
  "model_size": "base"
}
```

Supported Whisper sizes: `tiny`, `base`, `small`, `medium`. The default language is automatic detection. A supplied locale such as `en-US` is normalized to the language code expected by Whisper.

The listener captures a short command after "Hey Jarvis", transcribes it locally, then submits it through the normal JARVIS agent and permission policy. Actions requiring approval remain approval-gated. The listener does not bypass the kill switch or tool permissions.

## Speech endpoints

- `GET /api/v1/voice/options` reports installed Windows voices, local Piper voice and selected audio devices.
- `POST /api/v1/voice/speak` speaks text. The default is local Piper Amy.
- `POST /api/v1/voice/stop` stops active audio playback.
- `POST /api/v1/voice/listen` remains available for bounded user-initiated Windows dictation.

## Privacy and limitations

- Wake listening remains off after API restart until explicitly started. Once started, the opt-in preference persists across API restarts; calling the stop endpoint disables it persistently.
- Wake detection and Whisper transcription run locally after model download.
- No audio is uploaded for local Piper or local Whisper processing.
- ElevenLabs is a cloud service and is used only when explicitly selected.
- Current transcription is command-utterance based, not partial/word-by-word streaming STT.
- Real wake phrase accuracy and command recognition quality still require a spoken-session evaluation.
- Twi may be attempted through multilingual Whisper auto-detection, but its accuracy has not been validated and is not guaranteed.
- The voice runtime is Windows desktop oriented and expects the configured Fifine microphone and Echo Dot output.
