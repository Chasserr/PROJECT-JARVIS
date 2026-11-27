"""Local, read-only connectors: files, project repository, Obsidian vault.

Every path is resolved and checked against an explicit root before it is read.
A symlink that escapes the root is refused, not followed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..config import Settings
from ..skills.files import allowed_roots
from .base import Connector, SourceError, SourceHit, SourceState, SourceStatus

# Only these are ever decoded as text. Everything else is searchable by name.
TEXT_SUFFIXES = frozenset(
    {
        ".bat", ".cfg", ".conf", ".css", ".csv", ".env", ".gitignore", ".html", ".ini",
        ".js", ".json", ".jsx", ".log", ".md", ".mjs", ".ps1", ".py", ".rs", ".sh",
        ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
    }
)
_SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".next",
        ".idea", ".vscode", "data", ".cloud-attachments",
    }
)
_MAX_FILE_BYTES = 1_000_000
_MAX_SCAN_FILES = 20_000


def _snippet(text: str, needle: str, *, width: int = 180) -> str:
    lowered = text.lower()
    index = lowered.find(needle.lower())
    if index < 0:
        return text[:width].replace("\n", " ").strip()
    start = max(0, index - width // 2)
    end = min(len(text), index + width // 2)
    return " ".join(text[start:end].split())


def _read_text(path: Path, *, limit: int = _MAX_FILE_BYTES) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _walk(root: Path, *, max_files: int = _MAX_SCAN_FILES):
    """Yield files under ``root`` without following directory symlinks."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".")
        )
        for filename in sorted(filenames):
            seen += 1
            if seen > max_files:
                return
            yield Path(dirpath) / filename


def _guard(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SourceError(f"cannot resolve {path.name}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise SourceError("path escapes the authorised root")
    return resolved


class LocalFilesConnector(Connector):
    """Filenames and text content inside the configured search roots."""

    id = "local_files"
    label = "Local files"
    kind = "local"
    scopes = ("read",)
    requires = ("JARVIS_FILE_SEARCH_ROOTS",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _roots(self) -> list[Path]:
        if not self._settings.file_search_roots:
            return []
        return allowed_roots(self._settings)

    def status(self) -> SourceStatus:
        roots = self._roots()
        if not roots:
            return SourceStatus(
                SourceState.NOT_CONFIGURED,
                "set JARVIS_FILE_SEARCH_ROOTS to the folders JARVIS may read",
            )
        return SourceStatus(SourceState.CONNECTED, f"{len(roots)} root(s) authorised")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        needle = query.strip().lower()
        if not needle:
            return []
        hits: list[SourceHit] = []
        for root in self._roots():
            for path in _walk(root):
                name_match = needle in path.name.lower()
                text = _read_text(path) if path.suffix.lower() in TEXT_SUFFIXES else ""
                content_match = bool(text) and needle in text.lower()
                if not (name_match or content_match):
                    continue
                hits.append(
                    SourceHit(
                        source=self.id,
                        title=path.name,
                        locator=str(path),
                        snippet=_snippet(text, needle) if content_match else "",
                        metadata={
                            "root": str(root),
                            "size": path.stat().st_size if path.exists() else None,
                            # A filename hit is the stronger signal, so it wins.
                            "match": "filename" if name_match else "content",
                        },
                    )
                )
                if len(hits) >= limit:
                    return hits
        return hits

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        roots = self._roots()
        if not roots:
            raise SourceError("no local root is authorised")
        candidate = Path(locator).expanduser()
        for root in roots:
            try:
                resolved = _guard(candidate, root)
            except SourceError:
                continue
            if not resolved.is_file():
                raise SourceError(f"not a file: {resolved.name}")
            if resolved.suffix.lower() not in TEXT_SUFFIXES:
                raise SourceError(f"{resolved.suffix or 'no extension'} is not a text format")
            text = _read_text(resolved)
            return {
                "title": resolved.name,
                "locator": str(resolved),
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
            }
        raise SourceError("path is outside every authorised root")


class ProjectRepoConnector(Connector):
    """Read-only code search across this project's own repository."""

    id = "project_repo"
    label = "Project repository"
    kind = "local"
    scopes = ("read",)
    requires = ()

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _root(self) -> Path | None:
        root = self._settings.project_root
        if root is None:
            return None
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except OSError:
            return None
        return resolved if resolved.is_dir() else None

    def status(self) -> SourceStatus:
        root = self._root()
        if root is None:
            return SourceStatus(
                SourceState.NOT_CONFIGURED, "set JARVIS_PROJECT_ROOT to the repository folder"
            )
        return SourceStatus(SourceState.CONNECTED, f"repository root {root}")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        root = self._root()
        if root is None:
            raise SourceError("project root is not configured")
        needle = query.strip().lower()
        if not needle:
            return []
        hits: list[SourceHit] = []
        for path in _walk(root):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = _read_text(path, limit=400_000)
            if not text or needle not in text.lower():
                continue
            hits.append(
                SourceHit(
                    source=self.id,
                    title=str(path.relative_to(root)).replace("\\", "/"),
                    locator=str(path),
                    snippet=_snippet(text, needle),
                    metadata={"match": "content"},
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        root = self._root()
        if root is None:
            raise SourceError("project root is not configured")
        resolved = _guard(Path(locator), root)
        text = _read_text(resolved)
        return {
            "title": str(resolved.relative_to(root)).replace("\\", "/"),
            "locator": str(resolved),
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }


class ObsidianConnector(Connector):
    """Markdown notes from an explicitly configured Obsidian vault."""

    id = "obsidian"
    label = "Obsidian vault"
    kind = "local"
    scopes = ("read",)
    requires = ("JARVIS_OBSIDIAN_VAULT",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _vault(self) -> Path | None:
        if self._settings.obsidian_vault is None:
            return None
        try:
            resolved = Path(self._settings.obsidian_vault).expanduser().resolve(strict=True)
        except OSError:
            return None
        return resolved if resolved.is_dir() else None

    def status(self) -> SourceStatus:
        vault = self._vault()
        if vault is None:
            return SourceStatus(
                SourceState.NOT_CONFIGURED, "set JARVIS_OBSIDIAN_VAULT to your vault folder"
            )
        return SourceStatus(SourceState.CONNECTED, f"vault {vault}")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        vault = self._vault()
        if vault is None:
            raise SourceError("Obsidian vault is not configured")
        needle = query.strip().lower()
        hits: list[SourceHit] = []
        for path in _walk(vault):
            if path.suffix.lower() != ".md":
                continue
            text = _read_text(path)
            if needle not in path.stem.lower() and needle not in text.lower():
                continue
            heading = next(
                (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                path.stem,
            )
            hits.append(
                SourceHit(
                    source=self.id,
                    title=heading or path.stem,
                    locator=str(path),
                    snippet=_snippet(text, needle),
                    metadata={"note": path.stem, "tags": _tags(text)},
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        vault = self._vault()
        if vault is None:
            raise SourceError("Obsidian vault is not configured")
        resolved = _guard(Path(locator), vault)
        if resolved.suffix.lower() != ".md":
            raise SourceError("only Markdown notes can be read")
        text = _read_text(resolved)
        return {
            "title": resolved.stem,
            "locator": str(resolved),
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }


_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][\w/-]{1,40})")


def _tags(text: str) -> list[str]:
    return sorted(set(_TAG_RE.findall(text)))[:20]


__all__ = [
    "LocalFilesConnector",
    "ObsidianConnector",
    "ProjectRepoConnector",
    "TEXT_SUFFIXES",
]
