"""Skill package loader: manifest + skill.py, validated before registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.events import EventBus
from jarvis.security.audit import AuditLog
from jarvis.security.permissions import PermissionPolicy
from jarvis.skills.loader import SkillError, SkillLoader
from jarvis.tools.registry import ToolRegistry


def _write_skill(
    root: Path,
    name: str,
    *,
    manifest: dict | None = None,
    code: str | None = None,
) -> Path:
    package = root / name
    package.mkdir(parents=True)
    payload = manifest or {
        "name": name,
        "description": f"{name} test skill",
        "permission": "read_only",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    (package / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    (package / "skill.py").write_text(
        code
        or (
            "def run(args, context):\n    return {'ok': True, 'name': args.get('name', 'world')}\n"
        ),
        encoding="utf-8",
    )
    return package


def _loader(settings, db, box) -> tuple[SkillLoader, ToolRegistry]:
    registry = ToolRegistry(
        policy=PermissionPolicy({}),
        audit=AuditLog(db, box),
        events=EventBus(db),
        settings=settings,
    )
    return SkillLoader(registry), registry


def test_loads_valid_package_and_runs_it(settings, db, box, tmp_path: Path) -> None:
    _write_skill(tmp_path, "greeter")
    loader, registry = _loader(settings, db, box)

    loaded = loader.load_dir(tmp_path)

    assert [skill.name for skill in loaded] == ["greeter"]
    assert registry.has("greeter")
    assert loaded[0].missing_env == []


def test_rejects_duplicate_tool_name(settings, db, box, tmp_path: Path) -> None:
    _write_skill(tmp_path, "greeter")
    loader, _ = _loader(settings, db, box)
    loader.load_dir(tmp_path)

    with pytest.raises(SkillError, match="already registered"):
        loader.load_dir(tmp_path)


def test_reports_missing_environment_names(settings, db, box, tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "keyed",
        manifest={
            "name": "keyed",
            "description": "needs a key",
            "permission": "read_only",
            "requires_env": ["JARVIS_TEST_MISSING_KEY"],
        },
    )
    loader, _ = _loader(settings, db, box)

    loaded = loader.load_dir(tmp_path)

    assert loaded[0].missing_env == ["JARVIS_TEST_MISSING_KEY"]


def test_rejects_entry_path_traversal(settings, db, box, tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "sneaky",
        manifest={
            "name": "sneaky",
            "description": "bad entry",
            "entry": "../evil.py",
        },
    )
    loader, _ = _loader(settings, db, box)

    with pytest.raises(SkillError, match="entry"):
        loader.load_dir(tmp_path)


def test_rejects_manifest_name_mismatch(settings, db, box, tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "folder",
        manifest={"name": "other", "description": "mismatch"},
    )
    loader, _ = _loader(settings, db, box)

    with pytest.raises(SkillError, match="must match"):
        loader.load_dir(tmp_path)


def test_rejects_missing_run_function(settings, db, box, tmp_path: Path) -> None:
    _write_skill(tmp_path, "broken", code="value = 1\n")
    loader, _ = _loader(settings, db, box)

    with pytest.raises(SkillError, match="run"):
        loader.load_dir(tmp_path)


def test_ignores_non_skill_directories(settings, db, box, tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    _write_skill(tmp_path, "greeter")
    loader, registry = _loader(settings, db, box)

    loaded = loader.load_dir(tmp_path)

    assert [skill.name for skill in loaded] == ["greeter"]
    assert registry.has("greeter")
