"""Child process for :mod:`jarvis.tools.windows_sandbox`.

Reads one JSON request from stdin, dispatches an allowlisted pure-data
operation and writes one JSON response to stdout. It never touches the network,
the filesystem or another process, so the parent can safely run it under a
restricted low-integrity token.
"""

from __future__ import annotations

import json
import sys
from typing import Any

MAX_REQUEST_CHARS = 32_769


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    operation = request.get("operation")
    arguments = request.get("arguments")
    if not isinstance(arguments, dict):
        raise TypeError("arguments must be an object")
    if operation == "text.stats":
        value = arguments.get("text")
        if not isinstance(value, str) or len(value) > 8_000:
            raise ValueError("text must be a string up to 8,000 characters")
        return {
            "characters": len(value),
            "words": len(value.split()),
            "lines": len(value.splitlines()) if value else 0,
        }
    if operation == "json.summary":
        value = arguments.get("value")
        if not isinstance(value, (dict, list, str, int, float, bool, type(None))):
            raise ValueError("value must be JSON-compatible")
        if isinstance(value, dict):
            return {"kind": "object", "items": len(value), "keys": list(value)[:100]}
        if isinstance(value, list):
            return {"kind": "array", "items": len(value)}
        if isinstance(value, str):
            return {"kind": "string", "characters": len(value)}
        return {"kind": "scalar", "type": type(value).__name__}
    raise ValueError("operation is not allowlisted")


def main() -> int:
    try:
        raw = sys.stdin.readline(MAX_REQUEST_CHARS)
        if not raw or len(raw) > MAX_REQUEST_CHARS - 1:
            raise ValueError("request missing or exceeds 32 KB")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise TypeError("request must be an object")
        response = {"ok": True, "result": dispatch(request)}
    except Exception as exc:  # noqa: BLE001 - reported to the parent as data
        response = {"ok": False, "error": (str(exc) or type(exc).__name__)[:500]}
    sys.stdout.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
