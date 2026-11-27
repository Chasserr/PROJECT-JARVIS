from __future__ import annotations

import pytest

from jarvis.security.permissions import Decision, PermissionPolicy, PermissionTier
from jarvis.tools.manifest import ToolManifest


def _manifest(permission: PermissionTier) -> ToolManifest:
    return ToolManifest(
        name="demo.tool", description="demo", permission=permission, input_schema={"type": "object"}
    )


def test_default_tiers() -> None:
    policy = PermissionPolicy()
    assert policy.evaluate(_manifest(PermissionTier.READ_ONLY)) is Decision.ALLOW
    assert policy.evaluate(_manifest(PermissionTier.AUTONOMOUS)) is Decision.ALLOW
    assert policy.evaluate(_manifest(PermissionTier.CONFIRM)) is Decision.CONFIRM


def test_override_can_downgrade() -> None:
    policy = PermissionPolicy({"demo.tool": "read_only"})
    assert policy.effective(_manifest(PermissionTier.CONFIRM)) is PermissionTier.READ_ONLY


def test_override_cannot_upgrade_without_explicit_permission() -> None:
    policy = PermissionPolicy({"demo.tool": "autonomous"})
    assert policy.effective(_manifest(PermissionTier.CONFIRM)) is PermissionTier.CONFIRM
    upgraded = PermissionPolicy({"demo.tool": "autonomous"}, allow_upgrade=True)
    assert upgraded.effective(_manifest(PermissionTier.CONFIRM)) is PermissionTier.AUTONOMOUS


def test_dangerous_tool_cannot_be_autonomous() -> None:
    with pytest.raises(ValueError):
        ToolManifest(
            name="demo.danger",
            description="danger",
            permission=PermissionTier.AUTONOMOUS,
            dangerous=True,
        )
