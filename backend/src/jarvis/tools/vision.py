"""Image understanding through a local vision-capable model.

The only claim this module makes is one it can prove: it sends real image bytes
to a model and returns that model's own words. :func:`probe_vision` re-checks
that round-trip against an image whose contents are known, so "vision is
available" is never inferred from a model name in a dropdown.
"""

from __future__ import annotations

import base64
import binascii
import struct
import time
import zlib
from pathlib import Path
from typing import Any

import httpx

from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

MAX_IMAGE_BYTES = 8_000_000

# Ground truth for the self-test image.
PROBE_SHAPE = "circle"
PROBE_COLOUR = "red"


class VisionError(RuntimeError):
    """Raised when an image cannot be analysed."""


def make_probe_png() -> bytes:
    """A 256x256 PNG of a red circle on white, used to verify real vision."""
    size = 256
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = x - 128, y - 128
            row += bytes((220, 20, 20)) if dx * dx + dy * dy <= 80 * 80 else bytes((255, 255, 255))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def decode_image(*, image_base64: str | None, image_path: str | None, roots: list[Path]) -> bytes:
    """Decode an image from inline base64 or from an approved local path."""
    if image_base64:
        payload = image_base64.strip()
        if payload.startswith("data:"):
            _, _, payload = payload.partition(",")
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise VisionError(f"image_base64 is not valid base64: {exc}") from exc
    elif image_path:
        if not roots:
            raise VisionError(
                "reading an image from a path is disabled because no file_search_roots "
                "are configured; send the image inline as base64 instead"
            )
        target = Path(image_path).expanduser().resolve()
        if not any(target.is_relative_to(Path(root).resolve()) for root in roots):
            raise VisionError(f"image path is outside the approved roots: {target}")
        if not target.is_file():
            raise VisionError(f"image file does not exist: {target}")
        data = target.read_bytes()
    else:
        raise VisionError("provide image_base64 or image_path")

    if not data:
        raise VisionError("the image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise VisionError(
            f"image is {len(data)} bytes, over the {MAX_IMAGE_BYTES} byte limit"
        )
    return data


class OllamaVision:
    """Minimal Ollama client for image chat."""

    def __init__(self, base_url: str, model: str, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    async def describe(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        num_predict: int | None = None,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise VisionError("prompt must not be empty")
        payload: dict[str, Any] = {
            "model": model or self.model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt.strip(),
                    "images": [base64.b64encode(image).decode()],
                }
            ],
        }
        if num_predict is not None:
            payload["options"] = {"temperature": 0, "num_predict": num_predict}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self.base_url + "/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise VisionError(
                f"vision model returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionError(f"vision model is unreachable at {self.base_url}: {exc}") from exc

        message = body.get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise VisionError("the vision model returned an empty description")
        return {
            "description": text,
            "model": body.get("model", model or self.model),
            "mime": sniff_mime(image),
            "image_bytes": len(image),
            "latency_s": round(time.perf_counter() - started, 3),
        }


async def probe_vision(
    base_url: str, *, model: str, timeout: float = 120.0
) -> dict[str, Any]:
    """Prove the model really sees: a known image must yield a known answer."""
    image = make_probe_png()
    prompt = "What shape and what colour is the object? Answer in three words maximum."
    try:
        result = await OllamaVision(base_url, model, timeout=timeout).describe(
            image, prompt, num_predict=24
        )
    except VisionError as exc:
        return {"available": False, "model": model, "error": str(exc)}
    answer = result["description"].lower()
    matched = PROBE_SHAPE in answer and PROBE_COLOUR in answer
    return {
        "available": matched,
        "model": result["model"],
        "evidence": result["description"][:200],
        "expected": f"{PROBE_COLOUR} {PROBE_SHAPE}",
        "latency_s": result["latency_s"],
        "error": None if matched else "the model did not describe the known probe image",
    }


async def _vision_analyze(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    roots = [Path(item) for item in settings.file_search_roots]
    try:
        image = decode_image(
            image_base64=args.get("image_base64"),
            image_path=args.get("image_path"),
            roots=roots,
        )
        model = str(args.get("model") or settings.vision_model)
        if not model:
            raise VisionError("no vision model is configured (set JARVIS_VISION_MODEL)")
        prompt = str(
            args.get("prompt")
            or "Describe this image in detail. Name the objects, colours and setting."
        )
        result = await OllamaVision(
            settings.ollama_url, model, timeout=settings.vision_timeout_s
        ).describe(image, prompt)
    except VisionError as exc:
        return ToolResult(ok=False, error=str(exc))
    result["prompt"] = prompt
    return ToolResult(ok=True, output=result)


def register_vision_tool(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="vision.analyze",
            description=(
                "Analyse an image with a local vision model and return what it "
                "describes. Accepts an image inline as base64 (optionally a data "
                "URI) or a path inside the configured file search roots."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "image_base64": {
                        "type": "string",
                        "maxLength": 12_000_000,
                        "description": "Image bytes as base64, optionally a data: URI.",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Path to an image inside the approved file roots.",
                    },
                    "prompt": {
                        "type": "string",
                        "maxLength": 2000,
                        "description": "What to ask about the image.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Override the configured vision model.",
                    },
                },
                "additionalProperties": False,
            },
            tags=["vision", "multimodal", "image"],
        ),
        _vision_analyze,
    )


__all__ = [
    "MAX_IMAGE_BYTES",
    "OllamaVision",
    "VisionError",
    "decode_image",
    "make_probe_png",
    "probe_vision",
    "register_vision_tool",
    "sniff_mime",
]
