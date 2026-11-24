from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.skills import voice_control


def test_piper_speech_streams_local_chunks(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from piper import PiperVoice

    model = tmp_path / "amy.onnx"
    model.touch()
    monkeypatch.setattr(voice_control, "PIPER_MODEL_PATH", model)
    chunks = [
        SimpleNamespace(sample_rate=22_050, sample_channels=1, audio_int16_bytes=b"first"),
        SimpleNamespace(sample_rate=22_050, sample_channels=1, audio_int16_bytes=b"second"),
    ]
    monkeypatch.setattr(PiperVoice, "load", lambda *args, **kwargs: SimpleNamespace(
        synthesize=lambda text: iter(chunks)
    ))

    writes: list[bytes] = []

    class FakeOutput:
        def __init__(self, **kwargs):
            assert kwargs["samplerate"] == 22_050
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def write(self, data: bytes) -> None:
            writes.append(data)

    monkeypatch.setattr(voice_control.sd, "RawOutputStream", FakeOutput)
    monkeypatch.setattr(
        voice_control, "_audio_device",
        lambda index, kind: (5, {"name": "Speakers (2- Echo Dot-V34)"}),
    )
    result = voice_control.speak("Hello JARVIS", voice_control.PIPER_VOICE_NAME)
    assert result["provider"] == "Piper (local)"
    assert result["streaming"] is True
    assert writes == [b"first", b"second"]
