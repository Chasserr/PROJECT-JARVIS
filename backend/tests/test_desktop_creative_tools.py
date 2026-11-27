"""Desktop and creative tools: real behaviour, stubbed transports.

The HTTP layer of both backends is replaced with a scripted client, so these
tests prove the wiring, the permission tiers, the argument/response handling and
the way failures are reported — not a live machine. The live checks are recorded
in the session handover.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agent.team import AgentTeam
from jarvis.config import Settings
from jarvis.container import build_container
from jarvis.tools import creative as creative_module
from jarvis.tools import desktop as desktop_module
from jarvis.tools.creative import CreativeError, find_ffmpeg, probe_creative
from jarvis.tools.desktop import DesktopRuntimeError, probe_desktop
from jarvis.tools.registry import ApprovalRequired, ToolContext

from .conftest import FakeLLM

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def make_container(tmp_path: Path, **overrides):
    settings = Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        database_path=tmp_path / "test.sqlite3",
        api_token=None,
        ollama_embed_model="",
        capability_probes=False,
        project_root=tmp_path,
        file_search_roots=[tmp_path],
        **overrides,
    )
    return build_container(settings, llm=FakeLLM([]), embeddings=None)


def context(container) -> ToolContext:
    return ToolContext(
        memory=container.memory,
        settings=container.settings,
        events=container.events,
        db=container.db,
        box=container.box,
    )


class _Response:
    def __init__(self, payload=None, *, content: bytes = b"", status: int = 200) -> None:
        self._payload = payload
        self.content = content
        self.status_code = status
        self.text = str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Client:
    """Records requests and replays a queue of responses."""

    def __init__(self, responses, log: list) -> None:
        # Keep the caller's list: several requests share one scripted queue.
        self._responses = responses
        self._log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def request(self, method, url, **kwargs):
        self._log.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def patch_client(module, monkeypatch, responses, log):
    monkeypatch.setattr(
        module, "_http_client", lambda settings, timeout: _Client(responses, log)
    )


# --- desktop --------------------------------------------------------------


@pytest.mark.asyncio
async def test_desktop_status_reports_real_runtime_payload(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log: list = []
    patch_client(
        desktop_module,
        monkeypatch,
        [_Response({"screen": {"width": 1920, "height": 1080}, "active_window": "Notepad"})],
        log,
    )
    result = await container.registry.execute("desktop.status", {}, context(container))
    assert result.ok
    assert result.output["screen"] == {"width": 1920, "height": 1080}
    method, url, _ = log[0]
    assert (method, url) == ("GET", "http://127.0.0.1:8765/api/computer/status")


@pytest.mark.asyncio
async def test_desktop_action_needs_approval_and_forwards_the_payload(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log: list = []
    patch_client(desktop_module, monkeypatch, [_Response({"ok": True, "action": "click"})], log)
    ctx = context(container)
    with pytest.raises(ApprovalRequired):
        await container.registry.execute(
            "desktop.action", {"action": "click", "x": 10, "y": 20}, ctx
        )
    assert log == []
    result = await container.registry.execute(
        "desktop.action", {"action": "click", "x": 10, "y": 20}, ctx, approved=True
    )
    assert result.ok
    method, url, kwargs = log[0]
    assert method == "POST" and url.endswith("/api/computer/action")
    assert kwargs["json"] == {"action": "click", "x": 10, "y": 20}


@pytest.mark.asyncio
async def test_desktop_runtime_refusal_is_an_error_not_a_success(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log: list = []
    patch_client(
        desktop_module,
        monkeypatch,
        [_Response({"error": "That keyboard shortcut is not on the approved list."}, status=400)],
        log,
    )
    result = await container.registry.execute(
        "desktop.action", {"action": "hotkey", "keys": ["ctrl", "q"]}, context(container), approved=True
    )
    assert result.ok is False
    assert "not on the approved list" in (result.error or "")


@pytest.mark.asyncio
async def test_desktop_open_app_posts_to_the_existing_catalogue_endpoint(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log: list = []
    patch_client(
        desktop_module, monkeypatch, [_Response({"ok": True, "app": "Notepad"})], log
    )
    result = await container.registry.execute(
        "desktop.open_app", {"app": "Notepad"}, context(container), approved=True
    )
    assert result.ok and result.output["app"] == "Notepad"
    assert log[0][1].endswith("/api/desktop/open")
    assert log[0][2]["json"] == {"app": "Notepad"}


@pytest.mark.asyncio
async def test_desktop_screenshot_writes_a_real_png_file(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log: list = []
    patch_client(desktop_module, monkeypatch, [_Response(content=PNG)], log)
    result = await container.registry.execute(
        "desktop.screenshot", {}, context(container), approved=True
    )
    assert result.ok
    saved = Path(result.output["path"])
    assert saved.read_bytes() == PNG
    assert result.output["bytes"] == len(PNG)


@pytest.mark.asyncio
async def test_probe_desktop_requires_screen_geometry(tmp_path, monkeypatch) -> None:
    settings = make_container(tmp_path).settings
    log: list = []
    patch_client(desktop_module, monkeypatch, [_Response({"active_window": "x"})], log)
    failed = await probe_desktop(settings)
    assert failed["available"] is False

    patch_client(
        desktop_module,
        monkeypatch,
        [
            _Response({"screen": {"width": 1280, "height": 720}}),
            _Response({"attached": True, "foreground": "Notepad"}),
        ],
        log,
    )
    passed = await probe_desktop(settings)
    assert passed["available"] is True
    assert "1280x720" in passed["detail"]
    assert "Notepad" in passed["detail"]

    patch_client(
        desktop_module,
        monkeypatch,
        [
            _Response({"screen": {"width": 1280, "height": 720}}),
            _Response({"attached": False, "foreground": ""}),
        ],
        log,
    )
    detached = await probe_desktop(settings)
    assert detached["available"] is False
    assert "foreground window" in detached["error"]


@pytest.mark.asyncio
async def test_unreachable_runtime_is_reported_plainly(tmp_path, monkeypatch) -> None:
    import httpx

    settings = make_container(tmp_path).settings
    log: list = []
    patch_client(desktop_module, monkeypatch, [httpx.ConnectError("refused")], log)
    with pytest.raises(DesktopRuntimeError) as caught:
        await desktop_module._request(settings, "GET", "/api/computer/status")
    assert "unreachable" in str(caught.value)


# --- creative -------------------------------------------------------------

CHECKPOINT = "sd_xl_base_1.0.safetensors"


def comfy_stub(monkeypatch, responses):
    """Script the ComfyUI HTTP layer and return the request log."""
    log: list = []
    queue = list(responses)

    class _Scripted(_Client):
        def __init__(self) -> None:
            super().__init__([], log)

        async def request(self, method, url, **kwargs):
            log.append((method, url, kwargs))
            if not queue:
                raise AssertionError(f"unexpected request: {method} {url}")
            return queue.pop(0)

    monkeypatch.setattr(creative_module, "_http_client", lambda settings, timeout: _Scripted())
    return log


@pytest.mark.asyncio
async def test_image_generate_writes_the_png_the_backend_returned(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    log = comfy_stub(
        monkeypatch,
        [
            _Response({"prompt_id": "p1", "node_errors": {}}),
            _Response(
                {"p1": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [
                    {"filename": "out.png", "subfolder": "", "type": "output"}
                ]}}}}
            ),
            _Response(content=PNG),
        ],
    )
    result = await container.registry.execute(
        "image.generate",
        {"prompt": "a blue orb", "width": 512, "height": 512, "steps": 4, "seed": 7},
        context(container),
        approved=True,
    )
    assert result.ok, result.error
    assert Path(result.output["path"]).read_bytes() == PNG
    assert result.output["seed"] == 7
    queued = log[0][2]["json"]["prompt"]
    assert queued["4"]["inputs"]["ckpt_name"] == CHECKPOINT
    assert queued["6"]["inputs"]["text"] == "a blue orb"
    assert queued["5"]["inputs"]["width"] == 512


@pytest.mark.asyncio
async def test_image_edit_uploads_the_source_before_sampling(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    source = tmp_path / "input.png"
    source.write_bytes(PNG)
    log = comfy_stub(
        monkeypatch,
        [
            _Response({"name": "input.png", "subfolder": ""}),
            _Response({"prompt_id": "p2"}),
            _Response(
                {"p2": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [
                    {"filename": "edited.png", "type": "output"}
                ]}}}}
            ),
            _Response(content=PNG),
        ],
    )
    result = await container.registry.execute(
        "image.edit",
        {"image_path": str(source), "prompt": "make it red", "strength": 0.5, "steps": 4},
        context(container),
        approved=True,
    )
    assert result.ok, result.error
    assert log[0][1].endswith("/upload/image")
    workflow = log[1][2]["json"]["prompt"]
    assert workflow["3"]["inputs"]["denoise"] == 0.5
    assert workflow["11"]["inputs"]["image"] == "input.png"


@pytest.mark.asyncio
async def test_image_edit_refuses_paths_outside_the_approved_roots(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    comfy_stub(monkeypatch, [])
    outside = tmp_path.parent / "elsewhere.png"
    outside.write_bytes(PNG)
    result = await container.registry.execute(
        "image.edit",
        {"image_path": str(outside), "prompt": "x"},
        context(container),
        approved=True,
    )
    assert result.ok is False
    assert "outside the approved file roots" in (result.error or "")


@pytest.mark.asyncio
async def test_generation_failure_is_reported_with_the_backend_message(tmp_path, monkeypatch) -> None:
    container = make_container(tmp_path)
    comfy_stub(
        monkeypatch,
        [_Response({"prompt_id": "p3"}), _Response({"p3": {"status": {"status_str": "error", "messages": [["out of memory"]]}}})],
    )
    result = await container.registry.execute(
        "image.generate", {"prompt": "x", "steps": 4}, context(container), approved=True
    )
    assert result.ok is False
    assert "out of memory" in (result.error or "")


@pytest.mark.asyncio
async def test_probe_creative_checks_the_checkpoint_not_just_the_server(tmp_path, monkeypatch) -> None:
    settings = make_container(tmp_path).settings
    comfy_stub(
        monkeypatch,
        [
            _Response({"devices": [{"name": "cuda:0 RTX 5070"}]}),
            _Response({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["other.safetensors"]]}}}}),
        ],
    )
    failed = await probe_creative(settings)
    assert failed["available"] is False
    assert CHECKPOINT in failed["error"]

    comfy_stub(
        monkeypatch,
        [
            _Response({"devices": [{"name": "cuda:0 RTX 5070"}]}),
            _Response({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [[CHECKPOINT]]}}}}),
        ],
    )
    passed = await probe_creative(settings)
    assert passed["available"] is True
    assert passed["checkpoint"] == CHECKPOINT
    assert "ffmpeg" in passed["detail"]


def test_find_ffmpeg_honours_an_explicit_path(tmp_path) -> None:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path, ffmpeg_path=str(tmp_path / "nope.exe"))
    assert find_ffmpeg(settings) is None
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"x")
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path, ffmpeg_path=str(fake))
    assert find_ffmpeg(settings) == str(fake)


@pytest.mark.asyncio
async def test_video_edit_builds_a_real_ffmpeg_command(tmp_path, monkeypatch) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"x")
    container = make_container(tmp_path, ffmpeg_path=str(fake_ffmpeg))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not really a video")
    recorded: list[list[str]] = []

    def fake_run(ffmpeg, args, timeout):
        recorded.append(args)
        Path(args[-1]).write_bytes(b"mp4")

    monkeypatch.setattr(creative_module, "_run_ffmpeg", fake_run)
    result = await container.registry.execute(
        "video.edit",
        {"input_path": str(source), "start_s": 1.0, "end_s": 3.0, "width": 640, "fade": True},
        context(container),
        approved=True,
    )
    assert result.ok, result.error
    args = recorded[0]
    assert args[:2] == ["-ss", "1.00"]
    assert "-vf" in args and "scale=640:-2" in args[args.index("-vf") + 1]
    assert Path(result.output["path"]).exists()


# --- directory-level status -------------------------------------------------


def test_desktop_and_creative_are_connected_only_with_evidence(tmp_path) -> None:
    container = make_container(tmp_path)
    team = AgentTeam(container.registry)

    without = {role["id"]: role for role in team.describe({})}
    assert without["desktop"]["status"] == "partial"
    assert without["creative"]["status"] == "partial"

    probes = {
        "desktop_control": {"available": True, "screen": {"width": 1, "height": 1}},
        "creative_gen": {"available": True, "checkpoint": CHECKPOINT},
    }
    with_probes = {role["id"]: role for role in team.describe(probes)}
    assert with_probes["desktop"]["status"] == "connected"
    assert with_probes["creative"]["status"] == "connected"
    assert "desktop.action" in with_probes["desktop"]["available_tools"]
    assert "image.generate" in with_probes["creative"]["available_tools"]
    assert with_probes["desktop"]["missing_tools"] == []
    assert with_probes["creative"]["missing_tools"] == []


def test_creative_failure_explains_itself() -> None:
    error = CreativeError("ComfyUI is unreachable at http://127.0.0.1:8188")
    assert "unreachable" in str(error)
