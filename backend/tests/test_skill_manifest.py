import json

import pytest

from jarvis.skills.manifest import (
    SkillManifestError,
    load_skill_manifest,
    validate_skill_arguments,
)


def write_manifest(tmp_path, payload):
    path = tmp_path / "skills.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def sample_skill(**overrides):
    skill = {
        "skill_id": "notes.search",
        "description": "Search saved notes.",
        "permission": "read_only",
        "arguments": {"query": "Search phrase"},
        "argument_types": {"query": "string"},
    }
    skill.update(overrides)
    return skill


def test_loads_valid_manifest_and_preserves_declarative_metadata(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill()],
    })

    loaded = load_skill_manifest(path)

    assert loaded == [sample_skill()]


def test_rejects_duplicate_skill_ids(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(), sample_skill()],
    })

    with pytest.raises(SkillManifestError, match="Duplicate"):
        load_skill_manifest(path)


@pytest.mark.parametrize("permission", ["admin", "execute_python", "", None])
def test_rejects_unknown_permission_tiers(tmp_path, permission):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(permission=permission)],
    })

    with pytest.raises(SkillManifestError, match="permission"):
        load_skill_manifest(path)


def test_rejects_undeclared_fields_that_could_smuggle_code(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(handler="os.system", command="whoami")],
    })

    with pytest.raises(SkillManifestError, match="unsupported fields"):
        load_skill_manifest(path)


def test_rejects_unknown_manifest_versions(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 2,
        "skills": [sample_skill()],
    })

    with pytest.raises(SkillManifestError, match="schema_version"):
        load_skill_manifest(path)


def test_rejects_argument_names_outside_safe_identifier_format(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(
            arguments={"__class__": "unexpected"},
            argument_types={"__class__": "string"},
        )],
    })

    with pytest.raises(SkillManifestError, match="argument definition"):
        load_skill_manifest(path)


def test_capability_gated_skills_are_hidden_until_runtime_supports_them(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [
            sample_skill(),
            sample_skill(
                skill_id="creative.raea.render",
                requires=["raea"],
            ),
        ],
    })

    assert [item["skill_id"] for item in load_skill_manifest(path)] == ["notes.search"]
    enabled = load_skill_manifest(path, available_capabilities=frozenset({"raea"}))
    assert [item["skill_id"] for item in enabled] == [
        "notes.search", "creative.raea.render"
    ]


def test_rejects_invalid_json(tmp_path):
    path = tmp_path / "skills.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SkillManifestError, match="invalid JSON"):
        load_skill_manifest(path)


def test_rejects_missing_manifest(tmp_path):
    with pytest.raises(SkillManifestError, match="Cannot read"):
        load_skill_manifest(tmp_path / "missing.json")


def test_rejects_mismatched_argument_type_keys(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(argument_types={"other": "string"})],
    })

    with pytest.raises(SkillManifestError, match="matching keys"):
        load_skill_manifest(path)


def test_rejects_unknown_argument_types(tmp_path):
    path = write_manifest(tmp_path, {
        "schema_version": 1,
        "skills": [sample_skill(argument_types={"query": "python"})],
    })

    with pytest.raises(SkillManifestError, match="unsupported type"):
        load_skill_manifest(path)


def test_validates_runtime_argument_types_and_rejects_bool_as_integer():
    schema = {"limit": "integer", "paths": "array_of_strings", "device_index": "integer_or_null"}

    validate_skill_arguments(
        "files.search",
        {"limit": 20, "paths": ["C:/Users", "D:/Media"], "device_index": None},
        schema,
    )

    with pytest.raises(ValueError, match="expected integer"):
        validate_skill_arguments(
            "files.search",
            {"limit": True, "paths": ["C:/Users"], "device_index": None},
            schema,
        )


def test_rejects_non_finite_numbers():
    with pytest.raises(ValueError, match="expected number"):
        validate_skill_arguments(
            "creative.trim",
            {"start_seconds": float("nan")},
            {"start_seconds": "number"},
        )



def test_rejects_oversized_string_arguments():
    with pytest.raises(ValueError, match="size limits"):
        validate_skill_arguments("notes.search", {"query": "x" * 8_001}, {"query": "string"})


def test_rejects_oversized_or_excessive_string_arrays():
    with pytest.raises(ValueError, match="size limits"):
        validate_skill_arguments("media.concat", {"paths": ["x" * 2_001]}, {"paths": "array_of_strings"})
    with pytest.raises(ValueError, match="size limits"):
        validate_skill_arguments("media.concat", {"paths": ["x"] * 101}, {"paths": "array_of_strings"})
