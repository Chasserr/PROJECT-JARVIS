"""AES-256-GCM encryption for data at rest and a tamper-evident audit chain."""

from __future__ import annotations

import base64
import contextlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import Settings

_PREFIX = b"J1"
_NONCE_BYTES = 12


class CryptoError(RuntimeError):
    """Raised when a key is malformed or ciphertext fails authentication."""


def _decode_key(raw: str | bytes) -> bytes:
    if isinstance(raw, str):
        raw = raw.strip().encode("ascii")
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    if len(raw) == 32:
        return raw
    raise CryptoError("master key must be 32 raw bytes or base64-encoded 32 bytes")


class SecretBox:
    """Small wrapper around AES-256-GCM. Every value gets a fresh 96-bit nonce."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise CryptoError("AES-256 requires a 32-byte key")
        self._aead = AESGCM(key)

    @classmethod
    def from_settings(cls, settings: Settings) -> SecretBox:
        settings.ensure_dirs()
        if settings.master_key is not None:
            return cls(_decode_key(settings.master_key.get_secret_value()))
        key_path = settings.key_path
        if key_path.exists():
            return cls(_decode_key(key_path.read_bytes()))
        key = os.urandom(32)
        key_path.write_bytes(base64.b64encode(key))
        with contextlib.suppress(OSError):
            key_path.chmod(0o600)
        return cls(key)

    def encrypt_bytes(self, plaintext: bytes, *, context: bytes = b"jarvis") -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return _PREFIX + nonce + self._aead.encrypt(nonce, plaintext, context)

    def decrypt_bytes(self, blob: bytes, *, context: bytes = b"jarvis") -> bytes:
        if not blob.startswith(_PREFIX) or len(blob) <= len(_PREFIX) + _NONCE_BYTES:
            raise CryptoError("ciphertext has an unknown format")
        nonce = blob[len(_PREFIX) : len(_PREFIX) + _NONCE_BYTES]
        ciphertext = blob[len(_PREFIX) + _NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, ciphertext, context)
        except InvalidTag as exc:
            raise CryptoError("ciphertext authentication failed") from exc

    def encrypt_text(self, text: str, *, context: bytes = b"jarvis") -> bytes:
        return self.encrypt_bytes(text.encode("utf-8"), context=context)

    def decrypt_text(self, blob: bytes, *, context: bytes = b"jarvis") -> str:
        return self.decrypt_bytes(blob, context=context).decode("utf-8")

    def encrypt_json(self, value: Any, *, context: bytes = b"jarvis") -> bytes:
        return self.encrypt_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")), context=context
        )

    def decrypt_json(self, blob: bytes, *, context: bytes = b"jarvis") -> Any:
        return json.loads(self.decrypt_text(blob, context=context))


def read_key_file(path: Path) -> bytes:
    """Read a generated key file; useful for backups and tests."""
    return _decode_key(path.read_bytes())
