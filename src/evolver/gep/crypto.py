"""Symmetric crypto helpers (key gen, AES-256-GCM encrypt/decrypt, pack/unpack).

Equivalent to evolver/src/gep/crypto.js.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def encrypt(plaintext: bytes | str, key: bytes) -> bytes:
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    if len(key) != KEY_BYTES:
        raise ValueError(f"Key must be {KEY_BYTES} bytes")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    if len(key) != KEY_BYTES:
        raise ValueError(f"Key must be {KEY_BYTES} bytes")
    if len(ciphertext) < NONCE_BYTES + TAG_BYTES:
        raise ValueError("Ciphertext too short")
    nonce = ciphertext[:NONCE_BYTES]
    return AESGCM(key).decrypt(nonce, ciphertext[NONCE_BYTES:], None)


def pack(plaintext: bytes | str, key: bytes) -> str:
    raw = encrypt(plaintext, key)
    return base64.urlsafe_b64encode(raw).decode("ascii")


def unpack(packed: str, key: bytes) -> str:
    raw = base64.urlsafe_b64decode(packed.encode("ascii"))
    return decrypt(raw, key).decode("utf-8")
