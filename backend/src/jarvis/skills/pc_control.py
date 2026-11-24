from __future__ import annotations

import csv
import ctypes
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Deliberately fixed aliases: the planner cannot supply arbitrary shell commands or paths.
APP_ALIASES: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad.exe",),
    "calculator": ("calc.exe",),
    "explorer": ("explorer.exe",),
    "settings": ("ms-settings:",),
    "paint": ("mspaint.exe",),
    "brave": ("brave.exe", "brave"),
    "chrome": ("chrome.exe", "chrome"),
    "edge": ("msedge.exe", "msedge"),
    "obsidian": ("Obsidian.exe", "obsidian"),
    "codex": ("Codex.exe", "codex"),
    "vlc": ("vlc.exe", "vlc"),
}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _cpu_percent() -> float | None:
    if os.name != "nt":
        return None
    class _Times(ctypes.Structure):
        _fields_ = [("idle", ctypes.c_ulonglong), ("kernel", ctypes.c_ulonglong),
                    ("user", ctypes.c_ulonglong)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    first, second = _Times(), _Times()
    if not kernel.GetSystemTimes(ctypes.byref(first, 0), ctypes.byref(first, 8),
                                 ctypes.byref(first, 16)):
        return None
    time.sleep(0.2)
    if not kernel.GetSystemTimes(ctypes.byref(second, 0), ctypes.byref(second, 8),
                                 ctypes.byref(second, 16)):
        return None
    idle = second.idle - first.idle
    total = (second.kernel - first.kernel) + (second.user - first.user)
    return round(max(0.0, min(100.0, 100.0 * (1 - idle / total))), 1) if total else 0.0


def system_status() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop status currently supports Windows only.")
    memory = _MemoryStatus()
    memory.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ctypes.WinError(ctypes.get_last_error())
    disk = shutil.disk_usage(str(Path.home().anchor))
    return {
        "computer": os.environ.get("COMPUTERNAME", "Windows PC"),
        "platform": "Windows",
        "cpu_percent": _cpu_percent(),
        "memory": {"total_bytes": memory.ullTotalPhys, "available_bytes": memory.ullAvailPhys,
                   "percent_used": memory.dwMemoryLoad},
        "system_drive": {"total_bytes": disk.total, "free_bytes": disk.free,
                         "percent_used": round(100 * (disk.total - disk.free) / disk.total, 1)},
    }


def list_windows() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop window inspection currently supports Windows only.")
    user32 = ctypes.windll.user32
    windows: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type  # type: ignore[untyped-decorator]
    def callback(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
                if title:
                    windows.append({"title": title, "is_active": hwnd == user32.GetForegroundWindow(),
                                    "minimized": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(callback, 0)
    return {"windows": windows[:80], "count": len(windows), "truncated": len(windows) > 80}


def launch_app(alias: str) -> dict[str, Any]:
    key = alias.strip().lower()
    if key not in APP_ALIASES:
        raise ValueError(f"App '{alias}' is not in the approved launch list. Approved: {sorted(APP_ALIASES)}")
    candidates = APP_ALIASES[key]
    if key == "settings":
        startfile = getattr(os, "startfile", None)
        if not callable(startfile):
            raise RuntimeError("Windows URI launching is unavailable on this platform.")
        startfile(candidates[0])
        return {"launched": key, "method": "Windows URI"}
    executable = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
    if executable is None:
        if key in {"notepad", "calculator", "explorer", "paint"}:
            executable = candidates[0]
        else:
            raise FileNotFoundError(f"'{key}' is approved, but its executable was not found on this PC.")
    process = subprocess.Popen([executable], close_fds=True)
    return {"launched": key, "pid": process.pid, "executable": executable}


def running_processes(limit: int = 30) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                            text=True, check=True, timeout=10)
    rows = list(csv.reader(result.stdout.splitlines()))
    items = [{"name": row[0], "pid": int(row[1]), "session": row[2],
              "memory": row[4]} for row in rows if len(row) >= 5]
    items.sort(key=lambda item: str(item["name"]).lower())
    return {"processes": items[:limit], "count_returned": min(len(items), limit),
            "total_visible": len(items)}


# Window and file operations are deliberately constrained to visible windows and user folders.
def focus_window(title: str) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Window control currently supports Windows only.")
    needle = title.strip().casefold()
    if not needle or len(needle) > 200:
        raise ValueError("Provide a window title (1-200 characters).")
    user32 = ctypes.windll.user32
    matches: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type  # type: ignore[untyped-decorator]
    def callback(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                value = buffer.value.strip()
                if needle in value.casefold():
                    matches.append((hwnd, value))
        return True

    user32.EnumWindows(callback, 0)
    if not matches:
        raise FileNotFoundError(f"No visible window matched '{title}'.")
    if len(matches) > 1:
        return {"focused": False, "ambiguous": True,
                "matches": [name for _, name in matches[:10]]}
    hwnd, name = matches[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return {"focused": True, "title": name}


def close_window(title: str) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Window control currently supports Windows only.")
    needle = title.strip().casefold()
    if not needle or len(needle) > 200:
        raise ValueError("Provide a window title (1-200 characters).")
    user32 = ctypes.windll.user32
    matches: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type  # type: ignore[untyped-decorator]
    def callback(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                name = buffer.value.strip()
                if needle in name.casefold():
                    matches.append((hwnd, name))
        return True

    user32.EnumWindows(callback, 0)
    if not matches:
        raise FileNotFoundError(f"No visible window matched '{title}'.")
    if len(matches) > 1:
        return {"closed": False, "ambiguous": True,
                "matches": [name for _, name in matches[:10]]}
    hwnd, name = matches[0]
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE; app can prompt/save.
    return {"close_requested": True, "title": name,
            "note": "A graceful close request was sent; the app may ask to save changes."}


def _allowed_roots() -> list[Path]:
    home = Path.home().resolve()
    project_root = Path(__file__).resolve().parents[4]
    return [(home / name).resolve() for name in ("Desktop", "Downloads", "Documents")
            if (home / name).exists()] + [project_root.resolve()]


def _safe_user_path(raw: str) -> Path:
    candidate = Path(raw).expanduser().resolve()
    for root in _allowed_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise ValueError("Path must stay inside Desktop, Downloads, Documents, or the JARVIS project.")


def list_user_files(path: str, limit: int = 100) -> dict[str, Any]:
    limit = int(limit)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    target = _safe_user_path(path)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Folder not found: {target}")
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))[:limit]:
        try:
            stat = item.stat()
            entries.append({"name": item.name, "path": str(item), "type": "folder" if item.is_dir() else "file",
                            "size_bytes": None if item.is_dir() else stat.st_size})
        except OSError:
            continue
    return {"folder": str(target), "items": entries, "count": len(entries), "limit": limit}


def search_user_files(query: str, root: str, limit: int = 50) -> dict[str, Any]:
    limit = int(limit)
    needle = query.strip().casefold()
    if not needle or len(needle) > 120:
        raise ValueError("Search text must be between 1 and 120 characters.")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    base = _safe_user_path(root)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"Search folder not found: {base}")
    found: list[dict[str, str]] = []
    skipped = 0
    for current, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "__pycache__", ".venv"}]
        for name in dirs + files:
            if needle in name.casefold():
                found.append({"name": name, "path": str(Path(current) / name),
                              "type": "folder" if (Path(current) / name).is_dir() else "file"})
                if len(found) >= limit:
                    skipped = 1
                    break
        if skipped:
            break
    return {"root": str(base), "query": query, "matches": found,
            "count": len(found), "possibly_truncated": bool(skipped)}


def move_user_file(source: str, destination: str) -> dict[str, Any]:
    src = _safe_user_path(source)
    dst = _safe_user_path(destination)
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    if not dst.parent.exists() or not dst.parent.is_dir():
        raise FileNotFoundError(f"Destination folder not found: {dst.parent}")
    if dst.exists():
        raise FileExistsError(f"Destination already exists; refusing to overwrite: {dst}")
    if src.is_dir() and (dst == src or src in dst.parents):
        raise ValueError("Cannot move a folder into itself or one of its descendants.")
    shutil.move(str(src), str(dst))
    return {"moved": True, "source": str(src), "destination": str(dst)}


def capture_desktop() -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop capture currently supports Windows only.")
    import mss

    output_dir = Path(__file__).resolve().parents[3] / "data" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"desktop-{time.strftime('%Y%m%d-%H%M%S')}.png"
    output_path = output_dir / filename
    with mss.mss() as capture:
        monitor = capture.monitors[1]
        shot = capture.grab(monitor)
        from mss.tools import to_png
        png_data = to_png(shot.rgb, shot.size)
        if png_data is None:
            raise RuntimeError("Screenshot encoder returned no image data.")
        output_path.write_bytes(png_data)
    return {"captured": True, "path": str(output_path),
            "width": shot.width, "height": shot.height}


def click_desktop(x: int, y: int) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop interaction currently supports Windows only.")
    import pyautogui

    width, height = pyautogui.size()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"Coordinates must be within the screen: {width}x{height}.")
    pyautogui.FAILSAFE = True
    pyautogui.click(x=int(x), y=int(y), clicks=1, interval=0.1)
    return {"clicked": True, "x": int(x), "y": int(y), "screen": {"width": width, "height": height}}


def type_desktop_text(text: str) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop interaction currently supports Windows only.")
    if not text or len(text) > 2000:
        raise ValueError("Text must contain between 1 and 2000 characters.")
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.write(text, interval=0.01)
    return {"typed": True, "characters": len(text)}
