from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)


class WakeWordRuntime:
    """Opt-in, local wake-word and Whisper command listener for the preferred mic."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "running": False,
            "state": "stopped",
            "wake_word": "hey_jarvis",
            "stt_engine": "faster-whisper",
            "model": "small",
            "commands_processed": 0,
            "last_transcript": None,
            "last_error": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(
        self,
        on_command: Callable[[str], None],
        *,
        language: str | None = None,
        threshold: float = 0.55,
        model_size: str = "small",
    ) -> dict[str, Any]:
        if not 0.35 <= threshold <= 0.95:
            raise ValueError("Wake threshold must be between 0.35 and 0.95.")
        if model_size not in {"tiny", "base", "small", "medium"}:
            raise ValueError("Whisper model must be tiny, base, small, or medium.")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._status)
            self._stop.clear()
            self._status.update(
                running=True, state="starting", last_error=None,
                wake_threshold=threshold, language=language, model=model_size,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(on_command, language, threshold, model_size),
                name="jarvis-wake-listener",
                daemon=True,
            )
            self._thread.start()
            return dict(self._status)

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=4)
        with self._lock:
            if thread is None or not thread.is_alive():
                self._status.update(running=False, state="stopped")
                self._thread = None
            return dict(self._status)

    def _set(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def _run(
        self,
        on_command: Callable[[str], None],
        language: str | None,
        threshold: float,
        model_size: str,
    ) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            self._set(state="loading_wake_model")
            download_models(["hey_jarvis_v0.1"])
            wake_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._set(state="loading_stt_model")
            stt_model = WhisperModel(
                model_size, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1
            )
            from jarvis.skills.voice_control import _audio_device

            device_index, device = _audio_device(None, "input")
            self._set(state="listening", input_device=device["name"])
            sample_rate = 16_000
            frame_samples = 1_280  # openWakeWord expects 80 ms at 16 kHz.
            with sd.RawInputStream(
                device=device_index, samplerate=sample_rate, channels=1,
                dtype="int16", blocksize=frame_samples,
            ) as stream:
                while not self._stop.is_set():
                    raw, overflowed = stream.read(frame_samples)
                    if overflowed:
                        LOGGER.warning("JARVIS wake listener input overflow.")
                    audio = np.frombuffer(raw, dtype=np.int16)
                    scores = wake_model.predict(audio)
                    score = float(scores.get("hey_jarvis", 0.0))
                    if score < threshold:
                        continue
                    wake_model.reset()
                    self._set(state="capturing_command", wake_score=round(score, 3))
                    command_audio = self._capture_command(stream, frame_samples, sample_rate, np)
                    if command_audio.size == 0 or self._stop.is_set():
                        self._set(state="listening")
                        continue
                    self._set(state="transcribing")
                    segments, _ = stt_model.transcribe(
                        command_audio.astype(np.float32) / 32768.0,
                        language=(language.split("-")[0].lower() if language else None),
                        vad_filter=True,
                        beam_size=3,
                        condition_on_previous_text=False,
                    )
                    transcript = " ".join(segment.text.strip() for segment in segments).strip()
                    if transcript:
                        self._set(
                            last_transcript=transcript,
                            commands_processed=int(self.status()["commands_processed"]) + 1,
                        )
                        try:
                            on_command(transcript)
                        except Exception:
                            LOGGER.exception("JARVIS voice command callback failed.")
                    self._set(state="listening")
        except Exception as exc:
            LOGGER.exception("JARVIS wake listener stopped unexpectedly.")
            self._set(running=False, state="error", last_error=f"{type(exc).__name__}: {exc}")
        finally:
            if self._stop.is_set():
                self._set(running=False, state="stopped")

    @staticmethod
    def _capture_command(stream: Any, frame_samples: int, sample_rate: int, np: Any) -> Any:
        frames: list[Any] = []
        speech_started = False
        silence_frames = 0
        max_frames = int(12 * sample_rate / frame_samples)
        silence_limit = int(1.15 * sample_rate / frame_samples)
        start_timeout = int(2.5 * sample_rate / frame_samples)
        for index in range(max_frames):
            raw, _ = stream.read(frame_samples)
            frame = np.frombuffer(raw, dtype=np.int16).copy()
            frames.append(frame)
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            if rms > 350:
                speech_started = True
                silence_frames = 0
            elif speech_started:
                silence_frames += 1
                if silence_frames >= silence_limit:
                    break
            elif index >= start_timeout:
                break
        return np.concatenate(frames) if speech_started and frames else np.array([], dtype=np.int16)


wake_runtime = WakeWordRuntime()
