"""The agent-facing tool: ``phone.call``.

Placing a call is an external communication, so it is ``CONFIRM`` and
``dangerous``: the registry pauses it for explicit approval exactly like
``email.send``. When telephony is unconfigured the tool fails with the missing
setting names instead of pretending a call was placed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..security.permissions import PermissionTier
from ..tools.manifest import ToolManifest
from ..tools.registry import ToolContext, ToolResult
from .base import TelephonyError

if TYPE_CHECKING:
    from ..tools.registry import ToolRegistry
    from .gateway import VoiceGateway


def register_telephony_tool(registry: ToolRegistry, gateway: VoiceGateway) -> None:
    async def _call(args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context  # the gateway already holds the live settings
        try:
            call = await gateway.outbound(
                to=str(args["to"]), message=str(args.get("message", ""))
            )
        except TelephonyError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output=call)

    registry.register(
        ToolManifest(
            name="phone.call",
            description=(
                "Place a real phone call to one number and have JARVIS speak. "
                "Requires an approved telephony account; pauses for explicit approval."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "minLength": 8,
                        "maxLength": 20,
                        "description": "Destination in E.164 format, e.g. +15551234567.",
                    },
                    "message": {
                        "type": "string",
                        "maxLength": 1000,
                        "description": "Optional sentence spoken before the conversation starts.",
                    },
                },
                "required": ["to"],
                "additionalProperties": False,
            },
            timeout_s=45,
            tags=["phone", "voice", "external"],
        ),
        _call,
    )


__all__ = ["register_telephony_tool"]
