"""Privacy client — encrypt/decrypt sensitive GEP data at rest.

Uses AES-256-GCM via ``cryptography`` for symmetric encryption of
events, genes, and capsules stored in the memory directory.

Key management
--------------
* Master key is derived from ``EVOLVER_PRIVACY_PASSPHRASE`` via PBKDF2.
* If no passphrase is set, the client operates in passthrough mode
  (data is stored unencrypted — suitable for local-only deployments).
* Key file: ``~/.evomap/privacy-key`` (stores salt + iteration count,
  NOT the raw key).

Design notes
------------
* Each encrypted file has a random 12-byte nonce prepended.
* Tag is appended (16 bytes). Total overhead: 28 bytes per file.
* JSON files are encrypted as UTF-8 bytes; JSONL files are encrypted
  line-by-line so streaming still works.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_PASSPHRASE = "EVOLVER_PRIVACY_PASSPHRASE"
KEY_FILE = Path.home() / ".evomap" / "privacy-key"


def _derive_key(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a 32-byte AES key from *passphrase* using PBKDF2."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        raise RuntimeError("cryptography package required for privacy client")

    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = kdf.derive(passphrase.encode("utf-8"))
    return key, salt


def _load_or_create_key() -> bytes | None:
    """Return the derived AES key, or None if privacy is disabled."""
    passphrase = os.environ.get(ENV_PASSPHRASE)
    if not passphrase:
        return None

    if KEY_FILE.exists():
        data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
        salt = bytes.fromhex(data["salt"])
        key, _ = _derive_key(passphrase, salt)
        return key

    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key, salt = _derive_key(passphrase)
    KEY_FILE.write_text(json.dumps({"salt": salt.hex(), "iterations": 480_000}), encoding="utf-8")
    return key


def encrypt(data: bytes) -> bytes | None:
    """Encrypt *data* with AES-256-GCM. Returns None if privacy is disabled."""
    key = _load_or_create_key()
    if key is None:
        return None

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt(token: bytes) -> bytes | None:
    """Decrypt *token* with AES-256-GCM. Returns None if privacy is disabled."""
    key = _load_or_create_key()
    if key is None:
        return None

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = token[:12]
    ciphertext = token[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def encrypt_file(path: Path) -> bool:
    """Encrypt a single file in-place (atomic). Returns True if encrypted."""
    key = _load_or_create_key()
    if key is None:
        return False

    plaintext = path.read_bytes()
    result = encrypt(plaintext)
    if result is None:
        return False

    tmp = path.with_suffix(path.suffix + ".enc.tmp")
    tmp.write_bytes(result)
    tmp.replace(path)
    logger.debug("[Privacy] Encrypted %s", path)
    return True


def decrypt_file(path: Path) -> bool:
    """Decrypt a single file in-place (atomic). Returns True if decrypted."""
    key = _load_or_create_key()
    if key is None:
        return False

    token = path.read_bytes()
    result = decrypt(token)
    if result is None:
        return False

    tmp = path.with_suffix(path.suffix + ".dec.tmp")
    tmp.write_bytes(result)
    tmp.replace(path)
    logger.debug("[Privacy] Decrypted %s", path)
    return True
