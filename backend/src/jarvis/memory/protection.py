from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from typing import Any

_PREFIX = "dpapi:v1:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[Any]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_text(value: str) -> str:
    """Protect a UTF-8 value with Windows DPAPI, bound to the current Windows user."""
    if os.name != "nt":
        raise RuntimeError("JARVIS memory encryption requires Windows DPAPI; refusing plaintext storage.")
    raw = value.encode("utf-8")
    source, keepalive = _blob(raw)
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
                        wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    protect.restype = wintypes.BOOL
    if not protect(ctypes.byref(source), "JARVIS memory v1", None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return _PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(output.pbData)
        del keepalive


def unprotect_text(value: str) -> str:
    """Unprotect a value previously produced by protect_text."""
    if not value.startswith(_PREFIX):
        raise ValueError("Memory value is not DPAPI-protected; refusing an implicit plaintext fallback.")
    if os.name != "nt":
        raise RuntimeError("JARVIS memory decryption requires Windows DPAPI.")
    try:
        encrypted = base64.b64decode(value[len(_PREFIX):], validate=True)
    except ValueError as exc:
        raise ValueError("Invalid DPAPI memory payload.") from exc
    source, keepalive = _blob(encrypted)
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
                          ctypes.POINTER(_DataBlob), wintypes.LPVOID, wintypes.LPVOID,
                          wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    unprotect.restype = wintypes.BOOL
    if not unprotect(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output.pbData)
        del keepalive
