from __future__ import annotations

import pytest

from jarvis.skills import voice_control


def test_listen_rejects_invalid_language_code_before_recording() -> None:
    with pytest.raises(ValueError, match="valid language culture"):
        voice_control.listen(4, "not a language!")


def test_listen_rejects_language_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        voice_control, "available_options",
        lambda: {"recognition_languages": [{"culture": "en-US"}]},
    )
    with pytest.raises(ValueError, match="not installed"):
        voice_control.listen(4, "es-ES")


def test_listen_accepts_installed_language_and_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        voice_control, "available_options",
        lambda: {"recognition_languages": [{"culture": "en-US"}]},
    )
    class FakeInputStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, frames):
            return (b"\\x00\\x00" * frames, False)

    monkeypatch.setattr(voice_control, "_audio_device",
                        lambda index, kind: (1, {"name": "Microphone (fifine Microphone)"}))
    monkeypatch.setattr(voice_control.sd, "RawInputStream", FakeInputStream)
    monkeypatch.setattr(voice_control.subprocess, "run", lambda *a, **k: type(
        "Completed", (), {"returncode": 0, "stderr": "", "stdout":
        '{"recognized":false,"text":"","confidence":0}'} )())
    result = voice_control.listen(4, "en-US")
    assert result["recognized"] is False
    assert result["language"] == "en-US"
    assert result["engine"] == "Windows System.Speech"


def test_stop_speaking_stops_audio_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(voice_control.sd, "stop", lambda: calls.append("stop"))
    assert voice_control.stop_speaking() == {"stopped": True}
    assert calls == ["stop"]
