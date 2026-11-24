from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class RaeaUnavailable(RuntimeError):
    pass


class RaeaSkill:
    """Narrow, allowlisted bridge to raea's documented headless CLI."""

    def __init__(self, project_root: Path, *, executable: str | None = None) -> None:
        self.project_root = project_root.resolve()
        self.executable = executable or shutil.which("raea") or ""
        self.output_dir = (self.project_root / "backend" / "data" / "raea-output").resolve()

    def status(self) -> dict[str, Any]:
        if not self.executable:
            return {"available": False, "version": None, "capabilities": []}
        result = subprocess.run(
            [self.executable, "--version"], capture_output=True, text=True,
            timeout=10, check=False,
        )
        version = (result.stdout or result.stderr).strip()
        return {
            "available": result.returncode == 0,
            "version": version if result.returncode == 0 else None,
            "capabilities": ["media_probe", "media_analysis", "media_trim", "media_concat", "composition_render"] if result.returncode == 0 else [],
        }

    def _run(self, args: list[str], *, timeout: int = 120) -> dict[str, Any]:
        if not self.executable:
            raise RaeaUnavailable("raea CLI was not found on PATH.")
        result = subprocess.run(
            [self.executable, *args], capture_output=True, text=True,
            timeout=timeout, check=False, cwd=self.project_root,
        )
        payload = {"returncode": result.returncode, "stdout": result.stdout[-12000:],
                   "stderr": result.stderr[-12000:]}
        if result.returncode:
            raise RuntimeError(payload["stderr"] or payload["stdout"] or "raea command failed")
        return payload

    def probe_media(self, media_path: str) -> dict[str, Any]:
        path = Path(media_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Media path must point to a file.")
        return self._run(["media", "probe", str(path)], timeout=60)

    def analyze_media(self, media_path: str, analysis: str) -> dict[str, Any]:
        """Run one read-only, allowlisted media analysis through Raea."""
        allowed = {"loudness", "motion", "cuts", "freezes"}
        if analysis not in allowed:
            raise ValueError(f"Analysis must be one of: {', '.join(sorted(allowed))}.")
        path = Path(media_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Media path must point to a file.")
        result = self._run(["media", analysis, str(path)], timeout=180)
        return {"analysis": analysis, "media_path": str(path), **result}

    def _output_path(self, output_name: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\.mp4", output_name):
            raise ValueError("Output name must be a simple .mp4 filename.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = (self.output_dir / output_name).resolve()
        if output.parent != self.output_dir:
            raise ValueError("Output path is not allowed.")
        if output.exists():
            raise FileExistsError("Output already exists; choose a new filename to avoid overwriting.")
        return output

    def trim_media(self, media_path: str, start_seconds: float, end_seconds: float,
                   output_name: str) -> dict[str, Any]:
        source = Path(media_path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("Media path must point to a file.")
        if (not math.isfinite(start_seconds) or not math.isfinite(end_seconds)
                or start_seconds < 0 or end_seconds <= start_seconds):
            raise ValueError("Trim end must be greater than start, and start cannot be negative.")
        output = self._output_path(output_name)
        result = self._run(["media", "trim", str(source), "--from", str(start_seconds),
                            "--to", str(end_seconds), "-o", str(output)], timeout=900)
        result.update({"output_path": str(output), "output_exists": output.is_file()})
        return result

    def concat_media(self, media_paths: list[str], output_name: str) -> dict[str, Any]:
        if not 2 <= len(media_paths) <= 20:
            raise ValueError("Provide between 2 and 20 source media files.")
        sources = [Path(item).expanduser().resolve(strict=True) for item in media_paths]
        if any(not item.is_file() for item in sources):
            raise ValueError("Every source path must point to an existing file.")
        output = self._output_path(output_name)
        result = self._run(["media", "concat", *[str(item) for item in sources],
                            "-o", str(output)], timeout=1800)
        result.update({"output_path": str(output), "output_exists": output.is_file()})
        return result

    def render_composition(self, source_path: str, output_name: str) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve(strict=True)
        try:
            source.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("Composition must be inside the JARVIS project folder.") from exc
        if not source.is_file() or source.suffix.lower() not in {".tsx", ".html"}:
            raise ValueError("Only an existing .tsx or .html composition can be rendered.")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\.(mp4|png)", output_name):
            raise ValueError("Output name must be a simple .mp4 or .png filename.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = (self.output_dir / output_name).resolve()
        if output.parent != self.output_dir:
            raise ValueError("Output path is not allowed.")
        result = self._run(["render", str(source), "-o", str(output), "--quality", "high"],
                           timeout=900)
        result["output_path"] = str(output)
        result["output_exists"] = output.is_file()
        return result
