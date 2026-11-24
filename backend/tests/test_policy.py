from jarvis.agent.policy import PolicyEngine
from jarvis.models import PermissionTier, ToolCall


def test_permission_tiers_are_enforced():
    policy = PolicyEngine({
        "notes.read": PermissionTier.READ_ONLY,
        "pc.close_app": PermissionTier.CONFIRM_BEFORE_ACT,
        "weather.read": PermissionTier.AUTONOMOUS,
        "browser.click": PermissionTier.AUTONOMOUS,
    })

    read_only = policy.evaluate(ToolCall("notes.read"))
    assert read_only.allowed and not read_only.requires_approval

    confirm = policy.evaluate(ToolCall("pc.close_app"))
    assert not confirm.allowed and confirm.requires_approval

    autonomous = policy.evaluate(ToolCall("weather.read"))
    assert autonomous.allowed and not autonomous.requires_approval

    # High-impact actions remain approval-gated even if mistakenly configured
    # as autonomous in a manifest or registry.
    high_impact = policy.evaluate(ToolCall("browser.click"))
    assert not high_impact.allowed and high_impact.requires_approval

    unknown = policy.evaluate(ToolCall("unknown"))
    assert not unknown.allowed and not unknown.requires_approval


def test_kill_switch_blocks_even_read_only_tools():
    policy = PolicyEngine({"notes.read": PermissionTier.READ_ONLY}, kill_switch=True)
    decision = policy.evaluate(ToolCall("notes.read"))
    assert not decision.allowed
    assert not decision.requires_approval
    assert "kill switch" in decision.reason.lower()


def test_sensitive_desktop_and_file_actions_require_approval():
    policy = PolicyEngine({
        "apps.close": PermissionTier.AUTONOMOUS,
        "files.move": PermissionTier.AUTONOMOUS,
        "desktop.type_text": PermissionTier.AUTONOMOUS,
        "browser.type_text": PermissionTier.AUTONOMOUS,
        "browser.fill_field": PermissionTier.AUTONOMOUS,
    })

    for skill_id in (
        "apps.close",
        "files.move",
        "desktop.type_text",
        "browser.type_text",
        "browser.fill_field",
    ):
        decision = policy.evaluate(ToolCall(skill_id))
        assert not decision.allowed
        assert decision.requires_approval
