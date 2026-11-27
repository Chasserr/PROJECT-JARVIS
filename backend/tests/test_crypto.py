from __future__ import annotations

import base64

import pytest

from jarvis.security.crypto import CryptoError, SecretBox


def test_roundtrip_and_tamper() -> None:
    box = SecretBox(base64.b64decode(base64.b64encode(b"x" * 32)))
    blob = box.encrypt_text("hello JARVIS")
    assert blob != b"hello JARVIS"
    assert box.decrypt_text(blob) == "hello JARVIS"

    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(CryptoError):
        box.decrypt_text(bytes(tampered))


def test_context_is_authenticated() -> None:
    box = SecretBox(b"y" * 32)
    blob = box.encrypt_text("memory", context=b"memory")
    assert box.decrypt_text(blob, context=b"memory") == "memory"
    with pytest.raises(CryptoError):
        box.decrypt_text(blob, context=b"run")


def test_key_must_be_32_bytes() -> None:
    with pytest.raises(CryptoError):
        SecretBox(b"short")
