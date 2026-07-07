"""Encrypted trace-row decryption for trajectory export (G10.1 slice 2).

Ports the decryption half of ``evolver/src/gep/trajectoryExport.js`` /
``readTraceRowsDetailed``. Proxy trace rows are encrypted at the proxy with
AES-256-GCM under one of two key schemes:

* **node-secret** — the AES key is ``sha256('evomap-proxy-trace-v1:' + secret)``.
  A row may carry ``secret_version`` to select a specific keyring entry.
* **hub-key envelope** — a random AES key is RSA-OAEP-SHA256-wrapped with the
  Hub's public key (``hub_key_envelope``); only the Hub private key can unwrap
  it. If the hub key is absent/wrong, decryption falls back to the node secret.

Decryption is **fail-closed**: an undecryptable row raises unless
``allow_partial=True`` (then it is skipped and counted).
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Prefix mixed into the node-secret key derivation (matches the proxy writer).
_KEY_DERIVATION_PREFIX = "evomap-proxy-trace-v1:"

_MISSING_SECRET_MSG = "encrypted trace row cannot be exported without node secret"
_NODE_DECRYPT_MSG = "failed to decrypt encrypted trace row"
_HUB_DECRYPT_MSG = "failed to decrypt encrypted trace row with hub private key"


class TraceDecryptError(Exception):
    """Raised when an encrypted trace row cannot be decrypted (fail-closed)."""


def derive_node_key(node_secret: str) -> bytes:
    """Derive the 32-byte AES key from a node secret (matches the proxy writer)."""
    return hashlib.sha256((_KEY_DERIVATION_PREFIX + node_secret).encode("utf-8")).digest()


def _b64(data: str) -> bytes:
    return base64.b64decode(data)


def _aes_gcm_decrypt(key: bytes, row: dict[str, Any]) -> bytes:
    """AES-256-GCM decrypt; raises InvalidTag on auth failure / wrong key."""
    aes = AESGCM(key)
    # cryptography expects ciphertext || tag (tag is the trailing 16 bytes).
    data = _b64(row["ciphertext"]) + _b64(row["tag"])
    return aes.decrypt(_b64(row["iv"]), data, None)


def _hub_unwrap(private_pem: str, wrapped_key_b64: str) -> bytes:
    """RSA-OAEP-SHA256 unwrap the random AES key with the Hub private key."""
    try:
        private_key = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError) as exc:
        raise TraceDecryptError("invalid hub private key PEM") from exc
    if not isinstance(private_key, RSAPrivateKey):
        raise TraceDecryptError("hub private key is not an RSA key")
    return private_key.decrypt(
        _b64(wrapped_key_b64),
        OAEP(mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )


def _node_key_candidates(
    row: dict[str, Any],
    node_secret: str | None,
    node_secret_keyring: dict[Any, str] | None,
) -> list[bytes]:
    """Ordered AES keys to try for a node-secret row: keyring[version] then node_secret."""
    keys: list[bytes] = []
    version = row.get("secret_version")
    if version is not None and node_secret_keyring:
        secret = node_secret_keyring.get(version) or node_secret_keyring.get(str(version))
        if secret:
            keys.append(derive_node_key(str(secret)))
    if node_secret:
        keys.append(derive_node_key(node_secret))
    return keys


def decrypt_trace_row(
    row: dict[str, Any],
    *,
    node_secret: str | None = None,
    hub_private_key: str | None = None,
    node_secret_keyring: dict[Any, str] | None = None,
) -> dict[str, Any]:
    """Decrypt one trace row (plaintext rows pass through unchanged).

    Raises :class:`TraceDecryptError` (fail-closed) on undecryptable rows.
    """
    if not row.get("encrypted"):
        return row

    envelope = row.get("hub_key_envelope")
    envelope_dict = envelope if isinstance(envelope, dict) else None
    hub_tried = bool(envelope_dict and hub_private_key)

    def _decode(payload: bytes) -> dict[str, Any]:
        parsed = json.loads(payload.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}

    # 1. Try the hub private key to unwrap the AES key, then AES-GCM decrypt.
    if hub_tried and envelope_dict and hub_private_key:
        try:
            aes_key = _hub_unwrap(hub_private_key, envelope_dict["wrapped_key"])
            return _decode(_aes_gcm_decrypt(aes_key, row))
        except (InvalidTag, KeyError, TraceDecryptError, ValueError):
            pass  # fall through to node-secret keys

    # 2. Fall back to node-secret-derived keys (keyring[version] first).
    for key in _node_key_candidates(row, node_secret, node_secret_keyring):
        try:
            return _decode(_aes_gcm_decrypt(key, row))
        except (InvalidTag, ValueError):
            continue

    # 3. Nothing worked — fail closed with the most specific message.
    if not hub_tried and not _node_key_candidates(row, node_secret, node_secret_keyring):
        raise TraceDecryptError(_MISSING_SECRET_MSG)
    if hub_tried:
        raise TraceDecryptError(_HUB_DECRYPT_MSG)
    raise TraceDecryptError(_NODE_DECRYPT_MSG)


def read_trace_rows_detailed(
    input_path: Path | str,
    *,
    node_secret: str | None = None,
    hub_private_key: str | None = None,
    node_secret_keyring: dict[Any, str] | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Read trace rows, decrypting encrypted ones.

    Returns ``{"rows": [...], "stats": {encrypted_rows, decrypt_failures, ...}}``.
    Fail-closed on undecryptable rows unless ``allow_partial`` (then the row is
    skipped and counted).
    """
    rows_out: list[dict[str, Any]] = []
    encrypted = 0
    failures = 0

    for raw in Path(input_path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if not row.get("encrypted"):
            rows_out.append(row)
            continue
        encrypted += 1
        try:
            rows_out.append(
                decrypt_trace_row(
                    row,
                    node_secret=node_secret,
                    hub_private_key=hub_private_key,
                    node_secret_keyring=node_secret_keyring,
                )
            )
        except TraceDecryptError:
            if not allow_partial:
                raise
            failures += 1

    return {
        "rows": rows_out,
        "stats": {
            "encrypted_rows": encrypted,
            "decrypt_failures": failures,
            "total_rows": len(rows_out) + failures,
        },
    }
