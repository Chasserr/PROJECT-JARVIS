from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.agent.policy import PolicyEngine
from jarvis.models import PermissionTier, ToolCall
from jarvis.skills.manifest import load_skill_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "config" / "skills.json"


@pytest.fixture(scope="module")
def catalog():
    return load_skill_manifest(MANIFEST, available_capabilities=frozenset({"raea"}))


def test_every_manifest_skill_has_a_valid_permission_and_typed_schema(catalog):
    assert len(catalog) >= 30
    for skill in catalog:
        assert skill["permission"] in {"read_only", "autonomous", "confirm_before_act"}
        assert set(skill["arguments"]) == set(skill["argument_types"])
        assert all(isinstance(name, str) and name.isidentifier() for name in skill["arguments"])


def test_all_registered_sensitive_skill_families_are_approval_gated(catalog):
    # Explicit deny-by-default list: adding a new destructive/external action
    # requires an intentional policy review before it can ship.
    sensitive = {
        "apps.close", "files.move", "desktop.click", "desktop.type_text",
        "browser.click", "browser.type_text", "browser.fill_field", "browser.press_key",
        "creative.raea.render",
    }
    present = {item["skill_id"] for item in catalog}
    assert sensitive <= present
    permissions = {
        "read_only": PermissionTier.READ_ONLY,
        "autonomous": PermissionTier.AUTONOMOUS,
        "confirm_before_act": PermissionTier.CONFIRM_BEFORE_ACT,
    }
    policy = PolicyEngine({item["skill_id"]: permissions[item["permission"]] for item in catalog})
    for skill_id in sensitive:
        decision = policy.evaluate(ToolCall(skill_id))
        assert not decision.allowed, skill_id
        assert decision.requires_approval, skill_id


def test_every_high_impact_policy_entry_is_fail_closed_even_if_autonomous():
    policy = PolicyEngine({skill_id: PermissionTier.AUTONOMOUS
                           for skill_id in PolicyEngine.HIGH_IMPACT_SKILLS})
    for skill_id in PolicyEngine.HIGH_IMPACT_SKILLS:
        decision = policy.evaluate(ToolCall(skill_id))
        assert not decision.allowed, skill_id
        assert decision.requires_approval, skill_id


def test_kill_switch_blocks_every_registered_skill(catalog):
    permissions = {
        item["skill_id"]: {
            "read_only": PermissionTier.READ_ONLY,
            "autonomous": PermissionTier.AUTONOMOUS,
            "confirm_before_act": PermissionTier.CONFIRM_BEFORE_ACT,
        }[item["permission"]]
        for item in catalog
    }
    policy = PolicyEngine(permissions, kill_switch=True)
    for skill in catalog:
        decision = policy.evaluate(ToolCall(skill["skill_id"], {}))
        assert not decision.allowed, skill["skill_id"]
        assert not decision.requires_approval, skill["skill_id"]


def test_manifest_does_not_allow_runtime_code_or_permission_escalation_fields(tmp_path):
    original = json.loads(MANIFEST.read_text(encoding="utf-8"))
    skill = dict(original["skills"][0])
    skill["handler"] = "subprocess.Popen"
    original["skills"] = [skill]
    path = tmp_path / "hostile-skills.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fields"):
        load_skill_manifest(path)
