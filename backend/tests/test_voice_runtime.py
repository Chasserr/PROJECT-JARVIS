from __future__ import annotations

import pytest

from jarvis.skills.voice_runtime import WakeWordRuntime


def test_wake_runtime_starts_stopped() -> None:
    runtime = WakeWordRuntime()
    status = runtime.status()
    assert status["running"] is False
    assert status["state"] == "stopped"
    assert status["wake_word"] == "hey_jarvis"


@pytest.mark.parametrize("threshold", [0.0, 0.34, 0.96, 1.0])
def test_wake_runtime_rejects_unsafe_threshold(threshold: float) -> None:
    runtime = WakeWordRuntime()
    with pytest.raises(ValueError, match="threshold"):
        runtime.start(lambda _: None, threshold=threshold)


@pytest.mark.parametrize("model_size", ["large", "large-v3", "invalid"])
def test_wake_runtime_rejects_unbounded_model(model_size: str) -> None:
    runtime = WakeWordRuntime()
    with pytest.raises(ValueError, match="Whisper model"):
        runtime.start(lambda _: None, model_size=model_size)
