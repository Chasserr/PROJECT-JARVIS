from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, cast

import httpx
import pythoncom
import sounddevice as sd
import win32com.client


def available_options() -> dict[str, Any]:
    """Return installed Windows speech voices and recognition cultures."""
    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        tokens = voice.GetVoices()
        voices = [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
        del tokens
        del voice
    finally:
        pythoncom.CoUninitialize()
    script = r"""
Add-Type -AssemblyName System.Speech
[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
  ForEach-Object { @{ name=$_.Name; culture=$_.Culture.Name } } |
  ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip()[-800:] or "Could not enumerate speech recognizers."
        raise RuntimeError(detail)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    recognizers = json.loads(lines[-1]) if lines else []
    if isinstance(recognizers, dict):
        recognizers = [recognizers]
    devices: list[dict[str, Any]] = []
    for index, item in enumerate(sd.query_devices()):
        host_api = sd.query_hostapis(item["hostapi"])["name"]
        if "MME" not in host_api:
            continue
        if item["max_input_channels"] > 0 and "fifine microphone" in item["name"].lower():
            devices.append({"index": index, "name": item["name"], "kind": "input",
                            "host_api": host_api, "channels": item["max_input_channels"],
                            "selected": True})
        if item["max_output_channels"] > 0 and "echo dot" in item["name"].lower():
            devices.append({"index": index, "name": item["name"], "kind": "output",
                            "host_api": host_api, "channels": item["max_output_channels"],
                            "selected": True})
    if PIPER_MODEL_PATH.is_file():
        voices.append(PIPER_VOICE_NAME)
    return {
        "voices": voices,
        "recognition_languages": [
            {"name": item.get("name", ""), "culture": item.get("culture", "")}
            for item in recognizers
        ],
        "audio_devices": devices,
        "default_language": "en-US",
        "device_selection": "fixed_preferred_devices",
        "selected_input": "Microphone (fifine Microphone)",
        "selected_output": "Speakers (2- Echo Dot-V34)",
        "note": "JARVIS uses Fifine for microphone input and Echo Dot for speech output. Other microphone devices are hidden from JARVIS.",
    }


ELEVENLABS_VOICE_ID = "DODLEQrClDo8wCz460ld"
ELEVENLABS_VOICE_NAME = "Lauren B - Friendly & Comforting"
PIPER_VOICE_NAME = "Piper Amy - Local Female Voice"
PIPER_MODEL_PATH = Path(__file__).resolve().parents[4] / "data" / "voices" / "en_US-amy-medium.onnx"


def _speak_elevenlabs(text: str, output_index: int, output_device: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured.")
    ffmpeg = shutil.which("ffmpeg") or str(Path.home() / ".raea" / "bin" / "ffmpeg.exe")
    if not Path(ffmpeg).is_file():
        raise RuntimeError("FFmpeg is required for streaming ElevenLabs playback.")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
        "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", "pipe:1",
    ]
    decoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0)
    playback_error: list[BaseException] = []

    def play_decoded_audio() -> None:
        assert decoder.stdout is not None
        try:
            with sd.RawOutputStream(device=output_index, samplerate=44100, channels=1,
                                    dtype="int16") as output:
                while True:
                    chunk = decoder.stdout.read(8192)
                    if not chunk:
                        break
                    output.write(chunk)
        except Exception as exc:  # noqa: BLE001
            playback_error.append(exc)
            with suppress(Exception):
                decoder.kill()

    from contextlib import suppress
    reader = threading.Thread(target=play_decoded_audio, name="jarvis-tts-playback", daemon=True)
    reader.start()
    try:
        with httpx.stream(
            "POST", f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.55, "similarity_boost": 0.78,
                                   "style": 0.2, "use_speaker_boost": True},
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        ) as response:
            if response.is_error:
                detail = response.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(
                    f"ElevenLabs streaming request failed ({response.status_code}): {detail}"
                )
            assert decoder.stdin is not None
            received = 0
            for chunk in response.iter_bytes(4096):
                if chunk:
                    decoder.stdin.write(chunk)
                    received += len(chunk)
            decoder.stdin.close()
        reader.join(timeout=60)
        return_code = decoder.wait(timeout=5)
        if playback_error:
            raise RuntimeError(f"Audio playback failed: {playback_error[0]}")
        if received == 0 or return_code != 0:
            stderr = decoder.stderr.read().decode("utf-8", errors="replace") if decoder.stderr else ""
            raise RuntimeError(f"Could not decode streaming ElevenLabs audio: {stderr[-500:]}")
    except BaseException:
        with suppress(Exception):
            decoder.kill()
        raise
    finally:
        if reader.is_alive():
            reader.join(timeout=2)
        with suppress(Exception):
            decoder.stdout.close() if decoder.stdout else None
        with suppress(Exception):
            decoder.stderr.close() if decoder.stderr else None
    return {"spoken": True, "streaming": True, "characters": len(text),
            "voice": ELEVENLABS_VOICE_NAME, "provider": "ElevenLabs",
            "output_device": {"index": output_index, "name": output_device["name"]}}


def _speak_piper(text: str, output_index: int, output_device: dict[str, Any]) -> dict[str, Any]:
    if not PIPER_MODEL_PATH.is_file():
        raise RuntimeError(f"Local Piper voice model is missing: {PIPER_MODEL_PATH}")
    from piper import PiperVoice

    voice = PiperVoice.load(PIPER_MODEL_PATH)
    chunks = iter(voice.synthesize(text))
    first = next(chunks, None)
    if first is None:
        raise RuntimeError("Piper returned no speech audio.")
    with sd.RawOutputStream(
        device=output_index, samplerate=first.sample_rate,
        channels=first.sample_channels, dtype="int16",
    ) as output:
        output.write(first.audio_int16_bytes)
        for chunk in chunks:
            output.write(chunk.audio_int16_bytes)
    return {
        "spoken": True, "streaming": True, "characters": len(text),
        "voice": PIPER_VOICE_NAME, "provider": "Piper (local)",
        "output_device": {"index": output_index, "name": output_device["name"]},
    }


def speak(text: str, voice_name: str = PIPER_VOICE_NAME) -> dict[str, Any]:
    value = text.strip()
    if not value or len(value) > 4000:
        raise ValueError("Speech text must contain 1-4000 characters.")
    output_index, output_device = _audio_device(None, "output")
    if voice_name == ELEVENLABS_VOICE_NAME:
        try:
            return _speak_elevenlabs(value, output_index, output_device)
        except (RuntimeError, httpx.HTTPError) as exc:
            local_result = _speak_piper(value, output_index, output_device)
            local_result["fallback_reason"] = str(exc)[:300]
            return local_result
    if voice_name == PIPER_VOICE_NAME:
        return _speak_piper(value, output_index, output_device)
    pythoncom.CoInitialize()
    audio_path: Path | None = None
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voices = voice.GetVoices()
        selected = None
        for index in range(voices.Count):
            token = voices.Item(index)
            if token.GetDescription() == voice_name:
                selected = token
                break
        if selected is not None:
            voice.Voice = selected
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
            audio_path = Path(audio_file.name)
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(audio_path), 3, False)
        voice.AudioOutputStream = stream
        voice.Speak(value, 0)
        stream.Close()
        del stream
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
        with sd.RawOutputStream(device=output_index, samplerate=sample_rate,
                                channels=channels, dtype="int16") as output:
            output.write(frames)
        return {"spoken": True, "characters": len(value),
                "voice": voice.Voice.GetDescription(),
                "output_device": {"index": output_index, "name": output_device["name"]}}
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)
        pythoncom.CoUninitialize()


def stop_speaking() -> dict[str, bool]:
    """Immediately stop active sounddevice playback for JARVIS speech."""
    sd.stop()
    return {"stopped": True}


def _audio_device(device_index: int | None, kind: str) -> tuple[int, dict[str, Any]]:
    devices = sd.query_devices()
    preferred_name = "fifine microphone" if kind == "input" else "echo dot"
    if device_index is None:
        matches = [
            index for index, item in enumerate(devices)
            if preferred_name in item["name"].lower()
            and item["max_input_channels" if kind == "input" else "max_output_channels"] > 0
            and "MME" in sd.query_hostapis(item["hostapi"])["name"]
        ]
        if not matches:
            raise ValueError(f"Preferred {kind} device '{preferred_name}' is not available.")
        device_index = matches[0]
    if device_index < 0 or device_index >= len(devices):
        raise ValueError("Audio device index is not available. Refresh voice.options.")
    device = devices[device_index]
    if preferred_name not in device["name"].lower():
        raise ValueError(f"JARVIS is configured to use {preferred_name} for {kind}.")
    channel_count = device["max_input_channels" if kind == "input" else "max_output_channels"]
    if channel_count < 1:
        raise ValueError(f"Selected device cannot be used for {kind}.")
    return device_index, device


def listen(seconds: int = 6, language: str = "en-US",
           device_index: int | None = None) -> dict[str, Any]:
    duration = max(2, min(int(seconds), 15))
    culture_name = str(language).strip()
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", culture_name):
        raise ValueError("Use a valid language culture code such as en-US or es-ES.")
    available = available_options()["recognition_languages"]
    installed = {item["culture"].lower() for item in available}
    if culture_name.lower() not in installed:
        raise ValueError(
            f"Windows speech recognition for {culture_name} is not installed. "
            "Choose one of the installed languages reported by voice.options."
        )
    index, device = _audio_device(device_index, "input")
    sample_rate = 16000
    chunks: list[bytes] = []
    frames = int(sample_rate * duration)
    with sd.RawInputStream(device=index, samplerate=sample_rate, channels=1,
                           dtype="int16", blocksize=1024) as stream:
        remaining = frames
        while remaining > 0:
            count = min(1024, remaining)
            data, _ = stream.read(count)
            chunks.append(bytes(data))
            remaining -= count
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_path = Path(audio_file.name)
    try:
        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(chunks))
        script = r"""
Add-Type -AssemblyName System.Speech
$culture = [System.Globalization.CultureInfo]::GetCultureInfo('__CULTURE__')
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
try {
  $engine.SetInputToWaveFile('__AUDIO_PATH__')
  $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
  $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(3)
  $engine.BabbleTimeout = [TimeSpan]::FromSeconds(2)
  $result = $engine.Recognize([TimeSpan]::FromSeconds(__SECONDS__))
  if ($result) {
    @{ recognized = $true; text = $result.Text; confidence = [math]::Round($result.Confidence, 3) } | ConvertTo-Json -Compress
  } else {
    @{ recognized = $false; text = ''; confidence = 0 } | ConvertTo-Json -Compress
  }
} finally { $engine.Dispose() }
""".replace("__SECONDS__", str(duration)).replace("__CULTURE__", culture_name).replace(
            "__AUDIO_PATH__", str(audio_path).replace("'", "''")
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=duration + 12, check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip()[-1000:] or "Windows speech recognition failed."
            raise RuntimeError(detail)
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Speech recognition returned no response.")
        result = json.loads(lines[-1])
        if not isinstance(result, dict):
            raise TypeError("Speech recognition returned an invalid response.")
        result = cast(dict[str, Any], result)
        result["language"] = culture_name
        result["engine"] = "Windows System.Speech"
        result["input_device"] = {"index": index, "name": device["name"]}
        return result
    finally:
        audio_path.unlink(missing_ok=True)
