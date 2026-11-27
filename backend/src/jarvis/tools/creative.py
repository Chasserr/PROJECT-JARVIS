"""Creative tools: real image and video output from local backends.

Images come from the ComfyUI instance already installed on this machine
(``AI-Tools/ComfyUI`` with the SDXL checkpoint), through its HTTP API. Video is
produced with the local ffmpeg build: a generated still is animated, or several
stills are turned into a clip, and existing clips can be trimmed, scaled and
faded. No cloud provider and no API key are required.

The tools return the file they actually wrote, with its byte size; nothing here
reports a generation it did not perform. When ComfyUI is not running or the
checkpoint is missing, the error says exactly that.
"""

from __future__ import annotations

import asyncio
import json
import random
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

DEFAULT_NEGATIVE = "blurry, low quality, watermark, text, signature, extra limbs"
MAX_PROMPT = 1800


class CreativeError(RuntimeError):
    """The generation backend is unavailable or refused the job."""


def comfy_base(settings: Settings) -> str:
    return settings.comfyui_url.rstrip("/")


def find_ffmpeg(settings: Settings) -> str | None:
    """Locate a real ffmpeg binary; configuration wins, then PATH, then AI-Tools."""
    if settings.ffmpeg_path:
        candidate = Path(settings.ffmpeg_path)
        return str(candidate) if candidate.is_file() else None
    # Prefer the full build that ships with this machine's AI-Tools; a smaller
    # ffmpeg on PATH may lack libx264 and reject -preset.
    for candidate in (
        Path.home() / "AI-Tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def _output_dir(settings: Settings, kind: str) -> Path:
    folder = Path(settings.data_dir) / "generated" / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _input_path(raw: str, settings: Settings) -> Path:
    """Only files inside the approved roots may be read back as an input."""
    path = Path(raw).expanduser().resolve()
    roots = [root.resolve() for root in settings.file_search_roots] + [Path(settings.data_dir).resolve()]
    if not any(path.is_relative_to(root) for root in roots):
        raise CreativeError(f"{path} is outside the approved file roots")
    if not path.is_file():
        raise CreativeError(f"{path} is not a file")
    return path


def _http_client(settings: Settings, timeout: float) -> httpx.AsyncClient:
    """Seam for tests."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _client_call(
    settings: Settings,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    url = comfy_base(settings) + path
    try:
        async with _http_client(settings, timeout) as client:
            response = await client.request(
                method, url, json=json_body, files=files, data=data, params=params
            )
    except httpx.HTTPError as exc:
        raise CreativeError(f"ComfyUI is unreachable at {comfy_base(settings)}: {exc}") from exc
    if response.status_code >= 400:
        raise CreativeError(f"ComfyUI refused {path} ({response.status_code}): {response.text[:300]}")
    return response


async def comfy_models(settings: Settings) -> list[str]:
    """The checkpoint names ComfyUI will actually accept right now."""
    response = await _client_call(settings, "GET", "/object_info/CheckpointLoaderSimple")
    try:
        node = response.json()["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise CreativeError("ComfyUI did not report a checkpoint list") from exc
    return [str(item) for item in node]


async def probe_creative(settings: Settings) -> dict[str, Any]:
    """Prove the creative path exists: server answering, checkpoint present, ffmpeg found."""
    try:
        stats = (await _client_call(settings, "GET", "/system_stats", timeout=8.0)).json()
        models = await comfy_models(settings)
    except CreativeError as exc:
        return {"available": False, "error": str(exc)}
    if settings.comfyui_checkpoint not in models:
        return {
            "available": False,
            "error": (
                f"checkpoint {settings.comfyui_checkpoint!r} is not installed; "
                f"ComfyUI offers {', '.join(models[:5]) or 'nothing'}"
            ),
        }
    ffmpeg = find_ffmpeg(settings)
    device = ""
    try:
        device = str(stats.get("devices", [{}])[0].get("name") or "")
    except (AttributeError, IndexError, TypeError):
        device = ""
    return {
        "available": True,
        "checkpoint": settings.comfyui_checkpoint,
        "device": device,
        "ffmpeg": ffmpeg is not None,
        "detail": (
            f"ComfyUI on {comfy_base(settings)} with {settings.comfyui_checkpoint}"
            + (f" on {device}" if device else "")
            + ("; ffmpeg available for video" if ffmpeg else "; ffmpeg missing, so video is unavailable")
        ),
    }


async def _queue(settings: Settings, workflow: dict[str, Any]) -> str:
    response = await _client_call(
        settings,
        "POST",
        "/prompt",
        json_body={"prompt": workflow, "client_id": uuid.uuid4().hex},
        timeout=30.0,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CreativeError("ComfyUI did not return a queue receipt") from exc
    if payload.get("node_errors"):
        raise CreativeError(f"ComfyUI rejected the workflow: {json.dumps(payload['node_errors'])[:400]}")
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise CreativeError("ComfyUI queued nothing")
    return str(prompt_id)


async def _wait(settings: Settings, prompt_id: str, timeout_s: float) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        response = await _client_call(settings, "GET", f"/history/{prompt_id}", timeout=20.0)
        try:
            history = response.json()
        except ValueError:
            history = {}
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                last_error = json.dumps(messages)[-400:]
                raise CreativeError(f"ComfyUI failed the job: {last_error}")
            images: list[dict[str, Any]] = []
            for node in (entry.get("outputs") or {}).values():
                images.extend(node.get("images") or [])
            if images:
                return images
        await asyncio.sleep(1.5)
    raise CreativeError(f"ComfyUI did not finish within {timeout_s:.0f}s{(': ' + last_error) if last_error else ''}")


async def _fetch(settings: Settings, image: dict[str, Any]) -> bytes:
    response = await _client_call(
        settings,
        "GET",
        "/view",
        params={
            "filename": image.get("filename", ""),
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        },
        timeout=60.0,
    )
    body = response.content
    if not body.startswith(b"\x89PNG"):
        raise CreativeError("ComfyUI returned something that is not a PNG")
    return body


def _save(settings: Settings, kind: str, body: bytes) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = _output_dir(settings, kind) / f"{kind}-{stamp}-{uuid.uuid4().hex[:6]}.png"
    target.write_bytes(body)
    return target


def _text2img_workflow(
    settings: Settings,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    prefix: str,
) -> dict[str, Any]:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings.comfyui_checkpoint},
        },
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }


async def _generate_image(
    settings: Settings,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    prefix: str = "jarvis",
) -> Path:
    workflow = _text2img_workflow(settings, prompt, negative, width, height, steps, seed, prefix)
    prompt_id = await _queue(settings, workflow)
    images = await _wait(settings, prompt_id, settings.comfyui_timeout_s)
    body = await _fetch(settings, images[0])
    return _save(settings, "images", body)


async def _image_generate(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    prompt = str(args["prompt"]).strip()
    if not prompt:
        raise ValueError("prompt must not be empty")
    seed = int(args.get("seed") if args.get("seed") is not None else random.randint(1, 2**31 - 1))
    path = await _generate_image(
        settings,
        prompt,
        str(args.get("negative_prompt") or DEFAULT_NEGATIVE),
        int(args.get("width", 1024)),
        int(args.get("height", 1024)),
        int(args.get("steps", settings.creative_steps)),
        seed,
    )
    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "bytes": path.stat().st_size,
            "prompt": prompt,
            "seed": seed,
            "checkpoint": settings.comfyui_checkpoint,
        },
    )


async def _img2img_workflow(
    settings: Settings,
    source: Path,
    prompt: str,
    negative: str,
    strength: float,
    steps: int,
    seed: int,
) -> dict[str, Any]:
    upload = await _client_call(
        settings,
        "POST",
        "/upload/image",
        files={"image": (source.name, source.read_bytes(), "image/png")},
        data={"overwrite": "true"},
        timeout=60.0,
    )
    try:
        uploaded = str(upload.json()["name"])
    except (KeyError, ValueError) as exc:
        raise CreativeError("ComfyUI did not accept the source image") from exc
    subfolder = ""
    try:
        subfolder = str(upload.json().get("subfolder") or "")
    except ValueError:
        subfolder = ""
    name = f"{subfolder}/{uploaded}" if subfolder else uploaded
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": strength,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["10", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings.comfyui_checkpoint},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "jarvis_edit", "images": ["8", 0]}},
        "10": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["11", 0], "vae": ["4", 2]},
        },
        "11": {"class_type": "LoadImage", "inputs": {"image": name}},
    }


async def _image_edit(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    source = _input_path(str(args["image_path"]), settings)
    prompt = str(args["prompt"]).strip()
    if not prompt:
        raise ValueError("prompt must not be empty")
    seed = int(args.get("seed") if args.get("seed") is not None else random.randint(1, 2**31 - 1))
    strength = float(args.get("strength", 0.6))
    workflow = await _img2img_workflow(
        settings,
        source,
        prompt,
        str(args.get("negative_prompt") or DEFAULT_NEGATIVE),
        strength,
        int(args.get("steps", settings.creative_steps)),
        seed,
    )
    prompt_id = await _queue(settings, workflow)
    images = await _wait(settings, prompt_id, settings.comfyui_timeout_s)
    body = await _fetch(settings, images[0])
    target = _save(settings, "images", body)
    return ToolResult(
        ok=True,
        output={
            "path": str(target),
            "source": str(source),
            "bytes": target.stat().st_size,
            "prompt": prompt,
            "strength": strength,
            "seed": seed,
        },
    )


def _run_ffmpeg(ffmpeg: str, args: list[str], timeout: float) -> None:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise CreativeError(f"ffmpeg failed: {(result.stderr or result.stdout or '').strip()[-400:]}")


async def _render_clip(
    ffmpeg: str,
    source: Path,
    target: Path,
    seconds: float,
    fps: int,
    width: int,
    height: int,
    motion: str,
) -> None:
    frames = max(2, int(seconds * fps))
    scale = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if motion == "zoom_out":
        zoom = f"zoompan=z='if(lte(zoom,1.0),1.25,max(1.0,zoom-0.0015))':d={frames}:s={width}x{height}:fps={fps}"
    elif motion == "pan_right":
        zoom = (
            f"zoompan=z='1.12':x='(iw-iw/zoom)*on/{frames}':y='(ih-ih/zoom)/2'"
            f":d={frames}:s={width}x{height}:fps={fps}"
        )
    else:
        zoom = f"zoompan=z='min(1.25,1.0+0.0015*on)':d={frames}:s={width}x{height}:fps={fps}"
    _run_ffmpeg(
        ffmpeg,
        [
            "-loop", "1", "-i", str(source),
            "-vf", f"{scale},{zoom},format=yuv420p",
            "-t", f"{seconds:.2f}",
            "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart",
            str(target),
        ],
        timeout=180.0,
    )


async def _video_create(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    ffmpeg = find_ffmpeg(settings)
    if ffmpeg is None:
        raise CreativeError("ffmpeg was not found; set JARVIS_FFMPEG_PATH")
    seconds = float(args.get("seconds", 4))
    fps = int(args.get("fps", 24))
    width = int(args.get("width", 1280))
    height = int(args.get("height", 720))
    motion = str(args.get("motion", "zoom_in"))

    sources: list[Path] = []
    generated = None
    for raw in args.get("image_paths") or []:
        sources.append(_input_path(str(raw), settings))
    if not sources:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("provide either prompt or image_paths")
        generated = await _generate_image(
            settings, prompt, DEFAULT_NEGATIVE,
            int(args.get("source_width", 1024)), int(args.get("source_height", 576)),
            int(args.get("steps", settings.creative_steps)),
            int(args.get("seed") or random.randint(1, 2**31 - 1)),
            prefix="jarvis_video",
        )
        sources.append(generated)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = _output_dir(settings, "videos") / f"video-{stamp}-{uuid.uuid4().hex[:6]}.mp4"
    clips: list[Path] = []
    try:
        for index, source in enumerate(sources):
            clip = target.with_name(f"clip-{index}-{uuid.uuid4().hex[:6]}.mp4")
            await _render_clip(ffmpeg, source, clip, seconds, fps, width, height, motion)
            clips.append(clip)
        if len(clips) == 1:
            clips[0].replace(target)
        else:
            listing = target.with_name(f"list-{uuid.uuid4().hex[:6]}.txt")
            listing.write_text(
                "".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8"
            )
            _run_ffmpeg(
                ffmpeg,
                ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(target)],
                timeout=180.0,
            )
            listing.unlink(missing_ok=True)
    finally:
        for clip in clips:
            if clip.exists() and clip != target:
                clip.unlink(missing_ok=True)

    return ToolResult(
        ok=True,
        output={
            "path": str(target),
            "bytes": target.stat().st_size,
            "seconds": round(seconds * len(sources), 2),
            "fps": fps,
            "resolution": f"{width}x{height}",
            "motion": motion,
            "source_images": [str(item) for item in sources],
            "generated_image": str(generated) if generated else None,
            "note": "animated stills rendered locally with ffmpeg; no video-diffusion model is installed",
        },
    )


async def _video_edit(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    ffmpeg = find_ffmpeg(settings)
    if ffmpeg is None:
        raise CreativeError("ffmpeg was not found; set JARVIS_FFMPEG_PATH")
    source = _input_path(str(args["input_path"]), settings)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = _output_dir(settings, "videos") / f"edit-{stamp}-{uuid.uuid4().hex[:6]}.mp4"
    command: list[str] = []
    start = args.get("start_s")
    end = args.get("end_s")
    if start is not None:
        command += ["-ss", f"{float(start):.2f}"]
    command += ["-i", str(source)]
    if end is not None:
        command += ["-to", f"{float(end):.2f}"]
    filters: list[str] = []
    width = args.get("width")
    if width:
        filters.append(f"scale={int(width)}:-2")
    if args.get("fade"):
        filters.append("fade=t=in:st=0:d=0.6")
    if filters:
        command += ["-vf", ",".join(filters)]
    duration = args.get("duration_s")
    if duration:
        command += ["-t", f"{float(duration):.2f}"]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(target)]
    await asyncio.to_thread(_run_ffmpeg, ffmpeg, command, 240.0)
    return ToolResult(
        ok=True,
        output={
            "path": str(target),
            "source": str(source),
            "bytes": target.stat().st_size,
            "trimmed": start is not None or end is not None,
            "scaled_to": width,
        },
    )


_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "minLength": 1, "maxLength": MAX_PROMPT},
        "negative_prompt": {"type": "string", "maxLength": MAX_PROMPT},
        "width": {"type": "integer", "minimum": 256, "maximum": 1536},
        "height": {"type": "integer", "minimum": 256, "maximum": 1536},
        "steps": {"type": "integer", "minimum": 4, "maximum": 60},
        "seed": {"type": "integer", "minimum": 0},
    },
    "required": ["prompt"],
    "additionalProperties": False,
}


def register_creative_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="image.generate",
            description=(
                "Generate a real image from a text prompt with the local ComfyUI/SDXL "
                "runtime and save it as a PNG. Returns the file path and byte size."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema=_IMAGE_SCHEMA,
            timeout_s=300.0,
            tags=["creative", "image", "diffusion"],
        ),
        _image_generate,
    )
    registry.register(
        ToolManifest(
            name="image.edit",
            description=(
                "Edit an existing image inside the approved file roots with a prompt "
                "(img2img). strength controls how far it may move from the original."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "prompt": {"type": "string", "minLength": 1, "maxLength": MAX_PROMPT},
                    "negative_prompt": {"type": "string", "maxLength": MAX_PROMPT},
                    "strength": {"type": "number", "minimum": 0.1, "maximum": 0.95},
                    "steps": {"type": "integer", "minimum": 4, "maximum": 60},
                    "seed": {"type": "integer", "minimum": 0},
                },
                "required": ["image_path", "prompt"],
                "additionalProperties": False,
            },
            timeout_s=300.0,
            tags=["creative", "image", "edit"],
        ),
        _image_edit,
    )
    registry.register(
        ToolManifest(
            name="video.create",
            description=(
                "Create a real MP4: generate a still from a prompt (or use supplied "
                "images) and animate it with ffmpeg zoom/pan. Says plainly that the "
                "motion is rendered, not generated by a video model."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "maxLength": MAX_PROMPT},
                    "image_paths": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 4096},
                        "maxItems": 6,
                    },
                    "seconds": {"type": "number", "minimum": 1, "maximum": 10},
                    "fps": {"type": "integer", "minimum": 12, "maximum": 60},
                    "width": {"type": "integer", "minimum": 256, "maximum": 1920},
                    "height": {"type": "integer", "minimum": 256, "maximum": 1080},
                    "motion": {"type": "string", "enum": ["zoom_in", "zoom_out", "pan_right"]},
                    "seed": {"type": "integer", "minimum": 0},
                    "steps": {"type": "integer", "minimum": 4, "maximum": 60},
                },
                "additionalProperties": False,
            },
            timeout_s=300.0,
            tags=["creative", "video", "ffmpeg"],
        ),
        _video_create,
    )
    registry.register(
        ToolManifest(
            name="video.edit",
            description=(
                "Edit an existing clip with ffmpeg: trim by start/end, scale, or fade in. "
                "Writes a new MP4 and leaves the source untouched."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {
                    "input_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "start_s": {"type": "number", "minimum": 0},
                    "end_s": {"type": "number", "minimum": 0},
                    "duration_s": {"type": "number", "minimum": 0.5, "maximum": 600},
                    "width": {"type": "integer", "minimum": 256, "maximum": 1920},
                    "fade": {"type": "boolean"},
                },
                "required": ["input_path"],
                "additionalProperties": False,
            },
            timeout_s=300.0,
            tags=["creative", "video", "ffmpeg"],
        ),
        _video_edit,
    )


__all__ = [
    "CreativeError",
    "DEFAULT_NEGATIVE",
    "comfy_models",
    "find_ffmpeg",
    "probe_creative",
    "register_creative_tools",
]
