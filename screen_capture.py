"""Window-based Windows desktop capture fallback for sessions where GDI screen grabs fail."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import Image


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("width", ctypes.c_long),
        ("height", ctypes.c_long), ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD), ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD), ("x_pels", ctypes.c_long),
        ("y_pels", ctypes.c_long), ("clr_used", wintypes.DWORD),
        ("clr_important", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("header", _BitmapInfoHeader), ("colors", wintypes.DWORD * 3)]


gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


def _capture_window(hwnd: int) -> tuple[Image.Image, tuple[int, int]] | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 40 or height < 30 or width > 10000 or height > 10000:
        return None
    source_dc = user32.GetWindowDC(hwnd)
    if not source_dc:
        return None
    memory_dc = bitmap = old_object = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(source_dc)
        bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
        if not memory_dc or not bitmap:
            return None
        old_object = gdi32.SelectObject(memory_dc, bitmap)
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            return None
        info = _BitmapInfo()
        info.header.size = ctypes.sizeof(_BitmapInfoHeader)
        info.header.width = width
        info.header.height = -height
        info.header.planes = 1
        info.header.bit_count = 32
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        rows = gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
        )
        if rows != height:
            return None
        image = Image.frombuffer(
            "RGB", (width, height), bytes(buffer), "raw", "BGRX", 0, 1
        ).copy()
        return image, (rect.left, rect.top)
    finally:
        if old_object:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, source_dc)


def capture_desktop() -> Image.Image:
    # EnumWindows returns topmost-first; paste in reverse so topmost windows win.
    windows: list[tuple[int, int, int, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(min(title_length + 1, 512))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip().lower()
        # Some third-party overlay/security windows can block PrintWindow indefinitely.
        # Capture only ordinary app windows with known responsive PrintWindow behavior.
        if not any(token in title for token in (
            "settings", "brave", "cmd.exe", "program manager",
        )):
            return True
        rect = wintypes.RECT()
        if (
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            and rect.right - rect.left >= 40
            and rect.bottom - rect.top >= 30
        ):
            windows.append((hwnd, rect.left, rect.top, rect.right, rect.bottom))
        return True

    if not user32.EnumWindows(collect, 0):
        raise RuntimeError("Windows could not enumerate visible desktop windows")

    # Include monitors even if the virtual display origin is negative.
    left = min((item[1] for item in windows), default=0)
    top = min((item[2] for item in windows), default=0)
    right = max((item[3] for item in windows), default=2048)
    bottom = max((item[4] for item in windows), default=1152)
    left, top = min(left, 0), min(top, 0)
    width, height = max(1, right - left), max(1, bottom - top)
    if width > 10000 or height > 10000:
        raise RuntimeError("Detected desktop bounds are outside safe limits")

    canvas = Image.new("RGB", (width, height), (24, 24, 24))
    captured = 0
    for hwnd, _x1, _y1, _x2, _y2 in reversed(windows):
        result = _capture_window(hwnd)
        if result is None:
            continue
        image, (x, y) = result
        canvas.paste(image, (x - left, y - top))
        captured += 1
    if captured == 0:
        raise RuntimeError("Windows did not allow any visible window to be captured")
    return canvas
