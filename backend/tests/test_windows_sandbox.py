from __future__ import annotations

import os

import pytest

from jarvis.skills.windows_sandbox import SandboxError, run_restricted_worker


@pytest.mark.skipif(os.name != "nt", reason="Windows restricted-token worker only")
def test_restricted_worker_runs_allowlisted_text_stats() -> None:
    result = run_restricted_worker("text.stats", {"text": "JARVIS sandbox test\nsecond line"})
    assert result == {"characters": 31, "words": 5, "lines": 2}


@pytest.mark.skipif(os.name != "nt", reason="Windows restricted-token worker only")
def test_restricted_worker_rejects_unknown_operations() -> None:
    with pytest.raises(SandboxError, match="allowlisted"):
        run_restricted_worker("system.shell", {"command": "whoami"})


def test_restricted_worker_rejects_invalid_deadlines() -> None:
    with pytest.raises(ValueError, match="between 0.1 and 15"):
        run_restricted_worker("text.stats", {"text": "ok"}, timeout_seconds=30)


def test_restricted_worker_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="32 KB"):
        run_restricted_worker("text.stats", {"text": "x" * 32_750})
