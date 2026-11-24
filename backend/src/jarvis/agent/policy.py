from __future__ import annotations

from dataclasses import dataclass

from jarvis.models import PermissionTier, ToolCall


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


class PolicyEngine:
    # These actions can create external, financial, destructive or security-sensitive
    # consequences. Keep them gated even when routine actions are autonomous.
    HIGH_IMPACT_SKILLS = frozenset({
        "browser.click", "browser.press_key", "browser.type_text", "browser.fill_field",
        "apps.close", "files.move", "desktop.type_text",
        "payments.send", "payments.purchase", "payments.transfer",
        "messages.send", "email.send",
        "files.delete", "files.permanently_delete",
        "system.shutdown", "system.restart",
        "security.change_permissions", "security.share_externally",
    })

    def __init__(self, permissions: dict[str, PermissionTier] | None = None,
                 *, kill_switch: bool = False) -> None:
        self.permissions = permissions or {}
        self.kill_switch = kill_switch

    def evaluate(self, call: ToolCall) -> PolicyDecision:
        if self.kill_switch:
            return PolicyDecision(False, False, "JARVIS kill switch is active; all tool execution is disabled.")
        tier = self.permissions.get(call.skill_id)
        if tier is None:
            return PolicyDecision(False, False, "Skill is not registered or enabled.")
        if tier is PermissionTier.READ_ONLY:
            return PolicyDecision(True, False, "Read-only skill is allowed.")
        if tier is PermissionTier.CONFIRM_BEFORE_ACT or call.skill_id in self.HIGH_IMPACT_SKILLS:
            return PolicyDecision(False, True, "This action requires explicit user approval.")
        return PolicyDecision(True, False, "Autonomous execution is enabled for this routine skill.")
