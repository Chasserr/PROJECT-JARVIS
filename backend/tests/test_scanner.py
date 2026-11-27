"""Scanner tests: real report shapes, no network, no npm install.

Both scanners are replaced at the command boundary, so these tests assert how a
report is interpreted, not that pip-audit or npm are installed. A clean result,
a result with findings, a missing tool and a broken report must stay four
different states.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.agent.team import ROLE_REQUIRES
from jarvis.capabilities import probe_scanner
from jarvis.config import Settings
from jarvis.container import build_container
from jarvis.security.permissions import PermissionTier
from jarvis.tools import scanner as scanner_module
from jarvis.tools.scanner import scan_dependencies, scan_node, scan_python

from .conftest import FakeLLM

PIP_CLEAN = {
    "dependencies": [{"name": "requests", "version": "2.32.3", "vulns": []}],
    "fixes": [],
}

# Shape taken from a real `pip-audit -r` run against a pinned old release.
PIP_VULNERABLE = {
    "dependencies": [
        {
            "name": "requests",
            "version": "2.19.0",
            "vulns": [
                {
                    "id": "PYSEC-2018-28",
                    "fix_versions": ["2.20.0"],
                    "aliases": ["CVE-2018-18074"],
                    "description": "Sends an Authorization header to an http URI.",
                }
            ],
        },
        {"name": "idna", "version": "2.0", "vulns": []},
    ],
    "fixes": [],
}

NPM_VULNERABLE = {
    "metadata": {
        "vulnerabilities": {
            "info": 0,
            "low": 0,
            "moderate": 1,
            "high": 1,
            "critical": 0,
            "total": 2,
        },
        "dependencies": {"lodash": {}, "react": {}},
    },
    "vulnerabilities": {
        "lodash": {
            "name": "lodash",
            "severity": "high",
            "range": "<4.17.21",
            "via": [{"title": "Prototype pollution"}],
            "fixAvailable": True,
        },
        "react": {
            "name": "react",
            "severity": "moderate",
            "range": "<18.2.0",
            "via": ["lodash"],
            "fixAvailable": False,
        },
    },
}


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "environment": "test",
        "data_dir": tmp_path / "data",
        "database_path": tmp_path / "test.sqlite3",
        "api_token": None,
        "brave_api_key": None,
        "ollama_embed_model": "",
        "capability_probes": False,
        "project_root": tmp_path,
        "file_search_roots": [],
        "scanner_timeout_s": 10.0,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _fake_run(monkeypatch: pytest.MonkeyPatch, *, stdout: str, stderr: str = "", exit_code: int):
    calls: list[str] = []

    async def fake(argv, *, settings, cwd, timeout_s, max_chars):  # noqa: ANN001
        calls.append(argv[0])
        return {
            "command": argv,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": False,
            "cwd": str(cwd),
        }

    monkeypatch.setattr(scanner_module, "run_command", fake)
    return calls


def _fake_both(monkeypatch: pytest.MonkeyPatch, *, pip: dict, npm: dict):
    calls: list[str] = []

    async def fake(argv, *, settings, cwd, timeout_s, max_chars):  # noqa: ANN001
        chosen = npm if str(argv[0]).lower().startswith("npm") else pip
        calls.append(str(argv[0]))
        return {
            "command": argv,
            "exit_code": chosen["exit_code"],
            "stdout": json.dumps(chosen["body"]),
            "stderr": "",
            "truncated": False,
            "cwd": str(cwd),
        }

    monkeypatch.setattr(scanner_module, "run_command", fake)
    return calls


# ------------------------------------------------------------------ pip-audit


async def test_clean_scan_is_ran_with_no_findings(tmp_path, monkeypatch) -> None:
    _fake_run(monkeypatch, stdout=json.dumps(PIP_CLEAN), exit_code=0)
    report = await scan_python(make_settings(tmp_path))
    assert report["status"] == "ran"
    assert report["packages"] == 1
    assert report["vulnerable_packages"] == 0
    assert report["vulnerabilities"] == 0
    assert report["severity"] == {}


async def test_exit_code_one_with_findings_counts_as_a_completed_scan(
    tmp_path, monkeypatch
) -> None:
    _fake_run(monkeypatch, stdout=json.dumps(PIP_VULNERABLE), exit_code=1)
    report = await scan_python(make_settings(tmp_path))
    assert report["status"] == "ran"
    assert report["packages"] == 2
    assert report["vulnerable_packages"] == 1
    assert report["vulnerabilities"] == 1
    assert report["findings"][0] == {
        "package": "requests",
        "version": "2.19.0",
        "id": "PYSEC-2018-28",
        "fix_versions": ["2.20.0"],
    }
    # pip-audit carries no severity, so the summary says unknown, not "low".
    assert report["severity"] == {"unknown": 1}


async def test_missing_pip_audit_is_unavailable_not_clean(tmp_path, monkeypatch) -> None:
    _fake_run(
        monkeypatch, stdout="", stderr="No module named pip_audit", exit_code=1
    )
    report = await scan_python(make_settings(tmp_path))
    assert report["status"] == "unavailable"
    assert "pip-audit is not installed" in report["detail"]
    assert "vulnerabilities" not in report


async def test_broken_report_is_failed_not_clean(tmp_path, monkeypatch) -> None:
    _fake_run(monkeypatch, stdout="not json", stderr="boom", exit_code=2)
    report = await scan_python(make_settings(tmp_path))
    assert report["status"] == "failed"
    assert "no JSON" in report["detail"]


async def test_a_refused_runner_is_reported_as_unavailable(tmp_path, monkeypatch) -> None:
    async def refuse(argv, *, settings, cwd, timeout_s, max_chars):  # noqa: ANN001
        raise PermissionError("command 'python' is not allowlisted")

    monkeypatch.setattr(scanner_module, "run_command", refuse)
    report = await scan_python(make_settings(tmp_path))
    assert report["status"] == "unavailable"
    assert "PermissionError" in report["detail"]


# ------------------------------------------------------------------ npm audit


async def test_npm_is_not_applicable_without_a_lockfile(tmp_path, monkeypatch) -> None:
    calls = _fake_run(monkeypatch, stdout="{}", exit_code=0)
    report = await scan_node(make_settings(tmp_path))
    assert report["status"] == "not_applicable"
    assert "package-lock.json" in report["detail"]
    assert calls == []


async def test_npm_summarises_severity_and_findings(tmp_path, monkeypatch) -> None:
    project = tmp_path / "web"
    project.mkdir()
    (project / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scanner_module.shutil, "which", lambda name: "npm")
    _fake_run(monkeypatch, stdout=json.dumps(NPM_VULNERABLE), exit_code=1)

    report = await scan_node(make_settings(tmp_path))
    assert report["status"] == "ran"
    assert report["target"] == str(project)
    assert report["vulnerabilities"] == 2
    assert report["vulnerable_packages"] == 2
    assert report["severity"] == {"high": 1, "moderate": 1}
    by_name = {item["package"]: item for item in report["findings"]}
    assert by_name["lodash"]["advisories"] == ["Prototype pollution"]
    assert by_name["lodash"]["fix_available"] is True
    # A string entry in "via" is a transitive link, not an advisory.
    assert by_name["react"]["advisories"] == []


async def test_npm_without_a_binary_is_unavailable(tmp_path, monkeypatch) -> None:
    project = tmp_path / "web"
    project.mkdir()
    (project / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scanner_module.shutil, "which", lambda name: None)
    report = await scan_node(make_settings(tmp_path))
    assert report["status"] == "unavailable"
    assert "npm is not installed" in report["detail"]


# -------------------------------------------------------------------- summary


async def test_summary_totals_combine_both_scanners(tmp_path, monkeypatch) -> None:
    project = tmp_path / "web"
    project.mkdir()
    (project / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scanner_module.shutil, "which", lambda name: "npm")
    _fake_both(
        monkeypatch,
        pip={"body": PIP_VULNERABLE, "exit_code": 1},
        npm={"body": NPM_VULNERABLE, "exit_code": 1},
    )

    summary = await scan_dependencies(make_settings(tmp_path))
    assert summary["totals"]["scanners_ran"] == 2
    assert summary["totals"]["vulnerabilities"] == 3
    assert summary["totals"]["vulnerable_packages"] == 3
    assert summary["totals"]["by_severity"] == {"unknown": 1, "high": 1, "moderate": 1}
    assert summary["untrusted"] is True
    assert [item["status"] for item in summary["scanners"]] == ["ran", "ran"]


async def test_summary_says_when_no_scanner_could_run(tmp_path, monkeypatch) -> None:
    _fake_run(monkeypatch, stdout="", stderr="No module named pip_audit", exit_code=1)
    summary = await scan_dependencies(make_settings(tmp_path))
    assert summary["totals"]["scanners_ran"] == 0
    assert [item["status"] for item in summary["scanners"]] == ["unavailable", "not_applicable"]


# ------------------------------------------------------- tool and capability


def test_scanner_tool_is_registered_read_only_for_the_security_role(tmp_path) -> None:
    container = build_container(make_settings(tmp_path), llm=FakeLLM([]), embeddings=None)
    assert container.registry.has("security.scan")
    manifest = container.registry.get("security.scan").manifest
    assert manifest.permission is PermissionTier.READ_ONLY
    assert manifest.dangerous is False
    assert "security.scan" in container.agent.team.get("security").tools
    assert ROLE_REQUIRES["security"] == ("scanner",)


async def test_probe_requires_a_scan_that_actually_ran(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    _fake_run(monkeypatch, stdout=json.dumps(PIP_CLEAN), exit_code=0)
    available = await probe_scanner(settings)
    assert available["available"] is True
    assert available["packages"] == 1
    assert "scanned 1 packages" in available["detail"]

    _fake_run(monkeypatch, stdout="", stderr="No module named pip_audit", exit_code=1)
    unavailable = await probe_scanner(settings)
    assert unavailable["available"] is False
    assert "pip-audit" in unavailable["error"]


def test_the_security_role_leaves_partial_only_when_the_probe_passes(tmp_path) -> None:
    container = build_container(make_settings(tmp_path), llm=FakeLLM([]), embeddings=None)
    probes = {"scanner": {"available": False, "error": "no scanner"}}
    blocked = {item["id"]: item for item in container.agent.team.describe(probes)}
    assert blocked["security"]["status"] == "partial"
    assert "scanner" in blocked["security"]["unmet_requirements"]

    probes["scanner"] = {"available": True}
    probes["llm"] = {"available": True}
    passing = {item["id"]: item for item in container.agent.team.describe(probes)}
    assert passing["security"]["status"] == "connected"
    assert passing["security"]["status_detail"] == ""
