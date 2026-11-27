"""Filename search inside an explicit allowlist of local roots."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import Settings

_DEFAULT_ROOT_NAMES = ("Desktop", "Documents", "Downloads")


def allowed_roots(settings: Settings) -> list[Path]:
    if settings.file_search_roots:
        candidates = list(settings.file_search_roots)
    else:
        home = Path.home()
        candidates = [home / name for name in _DEFAULT_ROOT_NAMES]
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir():
            roots.append(resolved)
    return roots


def search_files(
    query: str,
    *,
    settings: Settings,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Case-insensitive filename substring search. Never follows directory symlinks."""

    needle = query.strip().lower()
    if not needle:
        return []
    limit = max_results or settings.file_search_max_results
    roots = allowed_roots(settings)
    results: list[dict[str, Any]] = []
    scanned = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            for filename in sorted(filenames):
                scanned += 1
                if scanned > settings.file_search_max_entries:
                    return results
                if needle not in filename.lower():
                    continue
                path = Path(dirpath) / filename
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(root):
                        continue
                    stat = resolved.stat()
                except OSError:
                    continue
                results.append(
                    {
                        "path": str(resolved),
                        "name": filename,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
                if len(results) >= limit:
                    return results
    return results


__all__ = ["allowed_roots", "search_files"]
