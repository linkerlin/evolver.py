"""Workspace keychain — secure per-workspace secret storage.

Tries ``keyring`` (OS credential manager) first, falls back to an
AES-256-GCM encrypted JSON file at ``~/.evomap/keychain.json``.

Equivalent to Node's ``evolver/src/gep/workspaceKeychain.js``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FALLBACK_PATH = Path.home() / ".evomap" / "keychain.json"


def _derive_key(password: bytes, salt: bytes) -> bytes:
    """Derive a 32-byte key from *password* and *salt* using PBKDF2-HMAC-SHA256."""
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations=100_000, dklen=32)


def _encrypt(plaintext: str, password: bytes) -> dict[str, str]:
    """Encrypt *plaintext* with AES-256-GCM. Return dict with base64 fields."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _decrypt(blob: dict[str, str], password: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = base64.b64decode(blob["salt"])
    nonce = base64.b64decode(blob["nonce"])
    ciphertext = base64.b64decode(blob["ciphertext"])
    key = _derive_key(password, salt)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------


class _KeyringBackend:
    """OS keyring via the ``keyring`` third-party package."""

    def __init__(self, service_name: str = "evolver-workspace") -> None:
        self._svc = service_name
        try:
            import keyring as kr

            self._kr = kr
        except ImportError:
            self._kr = None

    def available(self) -> bool:
        return self._kr is not None

    def set(self, key: str, value: str) -> None:
        if self._kr is None:
            raise RuntimeError("keyring not available")
        self._kr.set_password(self._svc, key, value)

    def get(self, key: str) -> str | None:
        if self._kr is None:
            return None
        return self._kr.get_password(self._svc, key)

    def delete(self, key: str) -> None:
        if self._kr is None:
            raise RuntimeError("keyring not available")
        self._kr.delete_password(self._svc, key)

    def list_keys(self) -> list[str]:
        if self._kr is None:
            return []
        try:
            return [item["username"] for item in self._kr.get_credential(self._svc, None) or []]
        except Exception:
            return []


class _FallbackBackend:
    """AES-256-GCM encrypted JSON file fallback."""

    def __init__(self, path: Path = _FALLBACK_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Derive password from machine-specific salt so the file is
        # tied to this machine but needs no user interaction.
        self._password = self._machine_password()

    @staticmethod
    def _machine_password() -> bytes:
        """Return a stable machine-specific password."""
        # Mix user profile path (stable across reboots) with a fixed pepper
        pepper = b"evolver-keychain-v1"
        seed = str(Path.home()).encode("utf-8") + pepper
        import hashlib

        return hashlib.sha256(seed).digest()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if "encrypted" in data:
                raw = _decrypt(data["encrypted"], self._password)
                return json.loads(raw)
            return data
        except Exception as exc:
            logger.warning("[Keychain] Failed to load fallback keychain: %s", exc)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        blob = _encrypt(payload, self._password)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"encrypted": blob}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def get(self, key: str) -> str | None:
        return self._load().get(key)

    def delete(self, key: str) -> None:
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def list_keys(self) -> list[str]:
        return list(self._load().keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceKeychain:
    """Unified keychain interface."""

    _kr: _KeyringBackend = field(default_factory=_KeyringBackend)
    _fb: _FallbackBackend = field(default_factory=_FallbackBackend)

    def _backend(self):
        if self._kr.available():
            return self._kr
        return self._fb

    def set(self, key: str, value: str) -> None:
        """Store *value* under *key*."""
        self._backend().set(key, value)
        logger.debug("[Keychain] Set %s", key)

    def get(self, key: str) -> str | None:
        """Retrieve value for *key*, or ``None``."""
        return self._backend().get(key)

    def delete(self, key: str) -> None:
        """Delete *key*."""
        self._backend().delete(key)
        logger.debug("[Keychain] Deleted %s", key)

    def list_keys(self) -> list[str]:
        """Return all stored keys."""
        return self._backend().list_keys()

    def clear(self) -> None:
        """Delete all stored keys."""
        for k in self.list_keys():
            self.delete(k)
        logger.info("[Keychain] Cleared all keys")
