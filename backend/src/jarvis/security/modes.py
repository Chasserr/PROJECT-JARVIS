"""Execution modes: how a run balances autonomy against human approval.

Modes are a *run-level* policy layered on top of the per-tool permission tiers.
The tiers say what a tool needs in principle; the mode says how much of that the
current run is allowed to skip.

- ``manual``     every step pauses, one at a time.
- ``supervised`` read-only tools run; confirmation tools pause.
- ``autonomous`` read-only and confirmation tools run; dangerous tools still pause.

``dangerous`` tools always pause in every mode. That is the security floor: no
mode, and no stored preference, can make a destructive tool run unattended.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .permissions import PermissionTier

if TYPE_CHECKING:
    from ..tools.manifest import ToolManifest

log = logging.getLogger(__name__)


class ExecutionMode(StrEnum):
    MANUAL = "manual"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


DEFAULT_MODE = ExecutionMode.SUPERVISED

MODE_DETAILS: dict[ExecutionMode, str] = {
    ExecutionMode.MANUAL: "Every tool step pauses for your approval, one step at a time.",
    ExecutionMode.SUPERVISED: "Read-only tools run; anything that changes state pauses for approval.",
    ExecutionMode.AUTONOMOUS: (
        "Runs read-only and confirmation tools without pausing; dangerous tools still pause."
    ),
}

# Tiers whose tools may run in autonomous mode without a prompt.
_AUTONOMOUS_TIERS = frozenset({PermissionTier.READ_ONLY, PermissionTier.AUTONOMOUS})


def requires_approval(
    mode: ExecutionMode,
    manifest: ToolManifest,
    effective_tier: PermissionTier,
) -> bool:
    """Decide whether this step must stop for a human before it runs.

    ``effective_tier`` is the policy-resolved tier (manifest default plus any
    user override), so lowering a tool's tier also lowers its prompting here.
    """
    if manifest.dangerous:
        return True
    if mode is ExecutionMode.MANUAL:
        return True
    if mode is ExecutionMode.SUPERVISED:
        return effective_tier not in _AUTONOMOUS_TIERS
    return False


def auto_approved(
    mode: ExecutionMode,
    manifest: ToolManifest,
    effective_tier: PermissionTier,
) -> bool:
    """Whether the mode itself authorises running this tool without a prompt.

    Autonomous mode covers read-only *and* confirmation tools, because that is
    exactly what the mode promises. ``dangerous`` tools keep their prompt.
    """
    if manifest.dangerous or mode is not ExecutionMode.AUTONOMOUS:
        return False
    return effective_tier in _AUTONOMOUS_TIERS or effective_tier is PermissionTier.CONFIRM


class ModeStore:
    """Persist the selected execution mode between restarts.

    The file is small and non-secret: a single ``{"mode": "..."}`` object. A
    corrupt or unknown value falls back to the default instead of failing a run.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path

    @property
    def path(self) -> Path | None:
        return self._path

    def get(self) -> ExecutionMode:
        if self._path is None or not self._path.exists():
            return DEFAULT_MODE
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return ExecutionMode(str(raw.get("mode", "")).strip().lower())
        except (OSError, ValueError, AttributeError):
            log.warning("agent mode file %s is unreadable; using %s", self._path, DEFAULT_MODE)
            return DEFAULT_MODE

    def set(self, mode: ExecutionMode) -> ExecutionMode:
        self._write(mode)
        return mode

    def _write(self, mode: ExecutionMode) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"mode": mode.value}, indent=2)
        handle, temp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp, self._path)
        except OSError:
            log.exception("could not persist agent mode to %s", self._path)
            try:
                os.unlink(temp)
            except OSError:
                pass


def mode_state(mode: ExecutionMode) -> dict[str, object]:
    """Serialisable description used by the API and the dashboard."""
    return {
        "mode": mode.value,
        "detail": MODE_DETAILS[mode],
        "available": [
            {
                "id": candidate.value,
                "label": candidate.value.title(),
                "detail": MODE_DETAILS[candidate],
                "available": True,
            }
            for candidate in (ExecutionMode.AUTONOMOUS, ExecutionMode.SUPERVISED, ExecutionMode.MANUAL)
        ],
    }
