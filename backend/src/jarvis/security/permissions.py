"""Permission tiers and the policy that resolves a tool's effective tier."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools.manifest import ToolManifest


class PermissionTier(StrEnum):
    READ_ONLY = "read_only"
    CONFIRM = "confirm"
    AUTONOMOUS = "autonomous"


class Decision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class PermissionPolicy:
    """Resolve manifest defaults plus user overrides.

    An override may lower a tier freely. Raising a tier is allowed only when
    ``allow_upgrade`` is explicitly true, so a typo cannot silently make a
    destructive tool autonomous.
    """

    def __init__(
        self, overrides: dict[str, str] | None = None, *, allow_upgrade: bool = False
    ) -> None:
        self._overrides: dict[str, PermissionTier] = {}
        for name, tier in (overrides or {}).items():
            self._overrides[name] = PermissionTier(tier)
        self._allow_upgrade = allow_upgrade

    def effective(self, manifest: ToolManifest) -> PermissionTier:
        override = self._overrides.get(manifest.name)
        if override is None:
            return manifest.permission
        if not self._allow_upgrade and _rank(override) > _rank(manifest.permission):
            return manifest.permission
        return override

    def evaluate(self, manifest: ToolManifest) -> Decision:
        tier = self.effective(manifest)
        if tier is PermissionTier.READ_ONLY or tier is PermissionTier.AUTONOMOUS:
            return Decision.ALLOW
        return Decision.CONFIRM


def _rank(tier: PermissionTier) -> int:
    return {
        PermissionTier.READ_ONLY: 0,
        PermissionTier.CONFIRM: 1,
        PermissionTier.AUTONOMOUS: 2,
    }[tier]
