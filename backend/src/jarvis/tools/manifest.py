"""Declarative skill/tool manifest. One manifest is one permission boundary."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field, field_validator, model_validator

from ..security.permissions import PermissionTier

_NAME_PATTERN = r"^[a-z][a-z0-9_.-]{1,63}$"


class ToolManifest(BaseModel):
    name: str = Field(pattern=_NAME_PATTERN)
    version: str = "1.0.0"
    description: str = Field(min_length=1, max_length=500)
    permission: PermissionTier = PermissionTier.CONFIRM
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    output_schema: dict[str, Any] | None = None
    timeout_s: float | None = Field(default=None, gt=0, le=300)
    tags: list[str] = Field(default_factory=list)
    requires_env: list[str] = Field(default_factory=list)
    dangerous: bool = False

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _valid_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as exc:
            raise ValueError(f"invalid JSON schema: {exc.message}") from exc
        if value.get("type") != "object":
            raise ValueError("tool input/output schemas must describe an object")
        return value

    @model_validator(mode="after")
    def _dangerous_needs_confirm(self) -> ToolManifest:
        if self.dangerous and self.permission is PermissionTier.AUTONOMOUS:
            raise ValueError("dangerous tools cannot be autonomous")
        return self

    def spec(self) -> dict[str, Any]:
        """OpenAI/Anthropic-compatible function description."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }
