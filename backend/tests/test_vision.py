"""Vision, capability probing and honest agent status.

Nothing here needs a live model: the HTTP layer is replaced by a stub, and the
status tests pass explicit probe results. A separate live check lives in the
session handover.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.agent.team import ROLE_REQUIRES
from jarvis.api.app import create_app
from jarvis.config import Settings
from jarvis.container import build_container
from jarvis.security.permissions import PermissionTier
from jarvis.tools import vision as vision_module
from jarvis.tools.vision import (
    MAX_IMAGE_BYTES,
    OllamaVision,
    VisionError,
    decode_image,
    make_probe_png,
    probe_vision,
    sniff_mime,
)

from .conftest import FakeLLM


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, answer: str = "A red circle") -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> _Response:
        self.calls.append((url, json or {}))
        return _Response(
            {"message": {"content": self.answer}, "model": (json or {}).get("model")}
        )


def _stub(monkeypatch: pytest.MonkeyPatch, answer: str) -> _Client:
    client = _Client(answer)
    monkeypatch.setattr(
        vision_module,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda *a, **k: client,
            HTTPStatusError=httpx.HTTPStatusError,
            HTTPError=httpx.HTTPError,
        ),
    )
    return client


@pytest.fixture
def stub_http(monkeypatch: pytest.MonkeyPatch) -> _Client:
    return _stub(monkeypatch, "A red circle")


# --------------------------------------------------------------- image plumbing


def test_probe_image_is_a_real_png() -> None:
    data = make_probe_png()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert sniff_mime(data) == "image/png"
    assert len(data) < MAX_IMAGE_BYTES


def test_sniff_mime_identifies_common_formats() -> None:
    assert sniff_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"
    assert sniff_mime(b"GIF89a" + b"\x00" * 8) == "image/gif"
    assert sniff_mime(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 4) == "image/webp"
    assert sniff_mime(b"not an image") == "application/octet-stream"


def test_decode_image_accepts_base64_and_data_uri() -> None:
    png = make_probe_png()
    encoded = base64.b64encode(png).decode()
    assert decode_image(image_base64=encoded, image_path=None, roots=[]) == png
    assert (
        decode_image(image_base64="data:image/png;base64," + encoded, image_path=None, roots=[])
        == png
    )


def test_decode_image_rejects_invalid_base64() -> None:
    with pytest.raises(VisionError, match="valid base64"):
        decode_image(image_base64="!!not base64!!", image_path=None, roots=[])


def test_decode_image_rejects_an_oversized_image() -> None:
    oversized = base64.b64encode(b"\x00" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(VisionError, match="over the"):
        decode_image(image_base64=oversized, image_path=None, roots=[])


def test_decode_image_refuses_paths_when_no_roots_are_configured(tmp_path) -> None:
    target = tmp_path / "shot.png"
    target.write_bytes(make_probe_png())
    with pytest.raises(VisionError, match="no file_search_roots"):
        decode_image(image_base64=None, image_path=str(target), roots=[])


def test_decode_image_rejects_a_path_outside_the_roots(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(make_probe_png())
    with pytest.raises(VisionError, match="outside the approved roots"):
        decode_image(image_base64=None, image_path=str(outside), roots=[allowed])


def test_decode_image_reads_an_approved_path(tmp_path) -> None:
    png = make_probe_png()
    target = tmp_path / "shot.png"
    target.write_bytes(png)
    assert decode_image(image_base64=None, image_path=str(target), roots=[tmp_path]) == png


# ------------------------------------------------------------- model round-trip


async def test_vision_sends_the_real_image_bytes(stub_http: _Client) -> None:
    png = make_probe_png()
    result = await OllamaVision("http://127.0.0.1:11434", "test-model").describe(png, "describe")
    url, payload = stub_http.calls[0]
    assert url.endswith("/api/chat")
    assert payload["messages"][0]["images"][0] == base64.b64encode(png).decode()
    assert result["description"] == "A red circle"
    assert result["image_bytes"] == len(png)


async def test_vision_rejects_an_empty_description(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, "")
    with pytest.raises(VisionError, match="empty description"):
        await OllamaVision("http://127.0.0.1:11434", "m").describe(make_probe_png(), "describe")


async def test_probe_vision_confirms_a_model_that_sees(stub_http: _Client) -> None:
    result = await probe_vision("http://127.0.0.1:11434", model="m")
    assert result["available"] is True
    assert result["evidence"] == "A red circle"


async def test_probe_vision_rejects_a_model_that_cannot_see(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, "I cannot see any image.")
    result = await probe_vision("http://127.0.0.1:11434", model="m")
    assert result["available"] is False
    assert "did not describe" in result["error"]


# ------------------------------------------------------------- honest status


def _probes(*satisfied: str) -> dict:
    everything = {key for keys in ROLE_REQUIRES.values() for key in keys}
    probes = {key: {"available": False, "error": "not implemented"} for key in everything}
    for key in satisfied:
        probes[key] = {"available": True}
    return probes


def test_roles_with_requirements_are_partial_without_evidence(settings: Settings) -> None:
    """Roles whose job needs a capability must not claim to be connected.

    Roles with no requirements are judged only on their tools existing, which the
    registry itself proves, so those may legitimately be connected.
    """
    container = build_container(settings, llm=FakeLLM([]), embeddings=None)
    described = container.agent.team.describe({})
    for item in described:
        if item["requires"]:
            assert item["status"] == "partial", item["id"]
            assert item["unmet_requirements"]


def test_status_follows_the_verified_capabilities(settings: Settings) -> None:
    container = build_container(settings, llm=FakeLLM([]), embeddings=None)
    by_id = {
        item["id"]: item
        for item in container.agent.team.describe(_probes("llm", "brave"))
    }
    # Roles whose whole job works with the tools that exist today.
    assert by_id["memory"]["status"] == "connected"
    assert by_id["critic"]["status"] == "connected"
    assert by_id["writer"]["status"] == "connected"
    # Research needs a working web search, which the probe satisfied.
    assert by_id["research"]["status"] == "connected"
    # Engineer needs code editing and a shell, and the probe set has neither.
    assert by_id["engineer"]["status"] == "partial"
    assert "code_edit" in by_id["engineer"]["unmet_requirements"]
    assert "shell" in by_id["engineer"]["unmet_requirements"]
    assert "code_edit" in by_id["engineer"]["status_detail"]
    assert "shell" in by_id["engineer"]["status_detail"]


def test_unimplemented_capabilities_explain_themselves() -> None:
    from jarvis.capabilities import UNIMPLEMENTED

    for key in ("scanner", "desktop_control", "creative_gen"):
        assert UNIMPLEMENTED[key].strip()
    # These are now implemented and probed at runtime, so they must not be
    # advertised as permanently missing.
    for key in ("code_edit", "shell", "browser_automation"):
        assert key not in UNIMPLEMENTED


def test_a_role_turns_connected_only_when_its_requirements_do(
    settings: Settings,
) -> None:
    container = build_container(settings, llm=FakeLLM([]), embeddings=None)
    partial = {i["id"]: i for i in container.agent.team.describe(_probes("llm"))}
    assert partial["research"]["status"] == "partial"
    assert "brave" in partial["research"]["unmet_requirements"]
    full = {i["id"]: i for i in container.agent.team.describe(_probes("llm", "brave"))}
    assert full["research"]["status"] == "connected"


def test_vision_tool_is_registered_for_the_team(settings: Settings) -> None:
    container = build_container(settings, llm=FakeLLM([]), embeddings=None)
    assert container.registry.has("vision.analyze")
    manifest = container.registry.get("vision.analyze").manifest
    assert manifest.permission is PermissionTier.READ_ONLY
    for role_id in ("research", "browser", "desktop", "creative"):
        role = container.agent.team.get(role_id)
        assert "vision.analyze" in role.tools


# ---------------------------------------------------------------- HTTP surface


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, llm=FakeLLM([]), embeddings=None))


def test_vision_endpoint_returns_the_model_answer(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_describe(self, image, prompt, model=None):  # noqa: ANN001
        return {
            "description": "A red circle",
            "model": "stub-model",
            "mime": sniff_mime(image),
            "image_bytes": len(image),
            "latency_s": 0.01,
        }

    monkeypatch.setattr(OllamaVision, "describe", fake_describe)
    response = _client(settings).post(
        "/api/v1/vision/analyze",
        json={"image_base64": base64.b64encode(make_probe_png()).decode(), "prompt": "what is this"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "A red circle"
    assert response.json()["model"] == "stub-model"


def test_vision_endpoint_rejects_bad_base64(settings: Settings) -> None:
    response = _client(settings).post("/api/v1/vision/analyze", json={"image_base64": "!!"})
    assert response.status_code == 400


def test_agents_endpoint_reports_derived_status(settings: Settings) -> None:
    body = _client(settings).get("/api/v1/agents").json()
    assert body["specialist_count"] == 10
    statuses = {item["id"]: item["status"] for item in body["agents"]}
    assert set(statuses.values()) <= {"connected", "partial", "blocked"}
    # Probes are disabled in tests, so no role that needs a capability may claim
    # to be connected on the strength of its declared settings alone.
    assert statuses["engineer"] == "partial"
    assert statuses["research"] == "partial"
    assert statuses["desktop"] == "partial"
