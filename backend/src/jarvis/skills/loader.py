"""Load declarative skill packages from ``skills/<name>/``.

A skill package is trusted local code: ``manifest.json`` declares the tool
contract and permission tier, ``skill.py`` exposes ``run(args, context)``.
The loader validates the manifest, refuses path traversal and name
mismatches, and reports missing environment variable *names* without reading
their values.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from ..tools.manifest import ToolManifest
from ..tools.registry import ToolError, ToolRegistry


class SkillError(RuntimeError):
    """A skill package is malformed or conflicts with an existing tool."""


class SkillManifest(ToolManifest):
    entry: str = Field(default="skill.py", max_length=120)

    @field_validator("entry")
    @classmethod
    def _safe_entry(cls, value: str) -> str:
        candidate = Path(value)
        if (
            candidate.name != value
            or candidate.suffix != ".py"
            or value.startswith(".")
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("entry must be a plain .py filename inside the skill package")
        return value


@dataclass
class LoadedSkill:
    name: str
    package: Path
    manifest: SkillManifest
    missing_env: list[str] = field(default_factory=list)


class SkillLoader:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def load_dir(self, root: Path) -> list[LoadedSkill]:
        root = Path(root)
        if not root.exists():
            return []
        if not root.is_dir():
            raise SkillError(f"skills path is not a directory: {root}")
        loaded: list[LoadedSkill] = []
        for package in sorted(root.iterdir()):
            if not package.is_dir() or package.name.startswith((".", "_")):
                continue
            if package.name == "__pycache__" or not (package / "manifest.json").is_file():
                continue
            loaded.append(self.load_package(package))
        return loaded

    def load_package(self, package: Path) -> LoadedSkill:
        package = Path(package)
        manifest_path = package / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(f"cannot read manifest for {package.name}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SkillError(f"manifest must be a JSON object: {manifest_path}")
        try:
            manifest = SkillManifest.model_validate(raw)
        except Exception as exc:
            raise SkillError(f"invalid manifest for {package.name}: {exc}") from exc
        if manifest.name != package.name:
            raise SkillError(
                f"manifest name {manifest.name!r} must match directory {package.name!r}"
            )

        entry = package / manifest.entry
        if entry.resolve().parent != package.resolve():
            raise SkillError(f"entry escapes the skill package: {manifest.entry}")
        if not entry.is_file():
            raise SkillError(f"entry file not found: {entry}")

        module = self._import_module(manifest.name, entry)
        runner = getattr(module, "run", None)
        if not callable(runner):
            raise SkillError(f"skill {manifest.name} must define a callable run(args, context)")

        try:
            self._registry.register(manifest, runner)
        except ToolError as exc:
            raise SkillError(str(exc)) from exc

        missing_env = [name for name in manifest.requires_env if not os.environ.get(name)]
        return LoadedSkill(
            name=manifest.name,
            package=package,
            manifest=manifest,
            missing_env=missing_env,
        )

    def _import_module(self, name: str, entry: Path) -> Any:
        module_name = f"jarvis_skill_{name.replace('.', '_').replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise SkillError(f"cannot import skill module: {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise SkillError(f"skill {name} failed to import: {type(exc).__name__}: {exc}") from exc
        return module


__all__ = ["LoadedSkill", "SkillError", "SkillLoader", "SkillManifest"]
