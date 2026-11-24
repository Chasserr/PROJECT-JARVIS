from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_SKILL_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ARGUMENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PERMISSIONS = frozenset({"read_only", "autonomous", "confirm_before_act"})
_ARGUMENT_TYPES = frozenset({
    "string", "integer", "number", "boolean", "array_of_strings", "integer_or_null",
})
_ROOT_KEYS = frozenset({"schema_version", "skills"})
_SKILL_KEYS = frozenset({
    "skill_id", "description", "permission", "arguments", "argument_types", "requires",
})


class SkillManifestError(ValueError):
    """Raised when a skill manifest is invalid or unsafe to load."""


def load_skill_manifest(
    path: Path,
    *,
    available_capabilities: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Load declarative skill metadata; manifests never import or execute code."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SkillManifestError(f"Cannot read skill manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SkillManifestError(
            f"Skill manifest contains invalid JSON at line {exc.lineno}."
        ) from exc

    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        raise SkillManifestError(
            "Manifest root must contain only schema_version and skills."
        )
    if payload.get("schema_version") != 1:
        raise SkillManifestError("Unsupported skill manifest schema_version.")
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SkillManifestError("Manifest skills must be a non-empty array.")

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_skills):
        required = {"skill_id", "description", "permission", "arguments", "argument_types"}
        if not isinstance(raw, dict) or not required <= set(raw):
            raise SkillManifestError(f"Skill entry {index} is missing required fields.")
        if set(raw) - _SKILL_KEYS:
            raise SkillManifestError(f"Skill entry {index} contains unsupported fields.")

        skill_id = raw["skill_id"]
        description = raw["description"]
        permission = raw["permission"]
        arguments = raw["arguments"]
        argument_types = raw["argument_types"]
        requires = raw.get("requires", [])

        if not isinstance(skill_id, str) or not _SKILL_ID.fullmatch(skill_id):
            raise SkillManifestError(f"Skill entry {index} has an invalid skill_id.")
        if skill_id in seen:
            raise SkillManifestError(f"Duplicate skill_id: {skill_id}.")
        seen.add(skill_id)
        if not isinstance(description, str) or not description.strip() or len(description) > 500:
            raise SkillManifestError(f"Skill '{skill_id}' has an invalid description.")
        if not isinstance(permission, str) or permission not in _PERMISSIONS:
            raise SkillManifestError(f"Skill '{skill_id}' has an invalid permission tier.")
        if not isinstance(arguments, dict) or not isinstance(argument_types, dict):
            raise SkillManifestError(f"Skill '{skill_id}' argument definitions must be objects.")
        if set(arguments) != set(argument_types):
            raise SkillManifestError(
                f"Skill '{skill_id}' argument descriptions and types must have matching keys."
            )
        for name, detail in arguments.items():
            if (not isinstance(name, str) or not _ARGUMENT_NAME.fullmatch(name)
                    or not isinstance(detail, str) or not detail.strip()
                    or len(detail) > 500):
                raise SkillManifestError(
                    f"Skill '{skill_id}' has an invalid argument definition."
                )
            if not isinstance(argument_types[name], str) or argument_types[name] not in _ARGUMENT_TYPES:
                raise SkillManifestError(
                    f"Skill '{skill_id}' has an unsupported type for argument '{name}'."
                )
        if not isinstance(requires, list) or any(
            not isinstance(item, str) or not _ARGUMENT_NAME.fullmatch(item)
            for item in requires
        ):
            raise SkillManifestError(f"Skill '{skill_id}' has invalid requirements.")

        # Capabilities are supplied by trusted runtime code, never by the manifest.
        if set(requires).issubset(available_capabilities):
            validated.append({
                "skill_id": skill_id,
                "description": description.strip(),
                "permission": permission,
                "arguments": dict(arguments),
                "argument_types": dict(argument_types),
                **({"requires": list(requires)} if requires else {}),
            })

    if not validated:
        raise SkillManifestError("No skills are enabled for the available capabilities.")
    return validated


def validate_skill_arguments(
    skill_id: str,
    arguments: dict[str, Any],
    argument_types: dict[str, str],
) -> None:
    """Fail closed on unknown argument keys and values of the wrong JSON type."""
    if set(arguments) != set(argument_types):
        raise ValueError(
            f"Invalid arguments for '{skill_id}'. Expected: {sorted(argument_types)}"
        )

    for name, expected in argument_types.items():
        value = arguments[name]
        valid = False
        if expected == "string":
            valid = isinstance(value, str)
        elif expected == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        elif expected == "boolean":
            valid = isinstance(value, bool)
        elif expected == "array_of_strings":
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        elif expected == "integer_or_null":
            valid = value is None or (isinstance(value, int) and not isinstance(value, bool))
        if valid and expected == "string" and len(value) > 8_000:
            valid = False
        if valid and expected == "array_of_strings":
            valid = len(value) <= 100 and all(len(item) <= 2_000 for item in value)
        if not valid:
            raise ValueError(
                f"Invalid value for '{skill_id}.{name}'; expected {expected} within size limits."
            )
