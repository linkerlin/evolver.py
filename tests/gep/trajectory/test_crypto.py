"""Encrypted trace-row decryption tests (G10.1 slice 2).

Ports the ``readTraceRowsDetailed`` decryption contracts from
``evolver/test/trajectoryExport.test.js``: node-secret + secret_version keyring,
hub-key envelope + node-secret fallback, fail-closed, and allow-partial.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from evolver.gep.trajectory import (
    TraceDecryptError,
    derive_node_key,
    read_trace_rows_detailed,
)

_PREFIX = "evomap-proxy-trace-v1:"


def _encrypt_with_key(row: dict, key: bytes, extra: dict | None = None) -> dict:
    iv = os.urandom(12)
    aes = AESGCM(key)
    ct = aes.encrypt(iv, json.dumps(row).encode("utf-8"), None)  # ciphertext || tag
    ciphertext, tag = ct[:-16], ct[-16:]
    out = {
        "encrypted": True,
        "algorithm": "aes-256-gcm",
        "payload_schema": "prism_trace_row",
        "iv": base64.b64encode(iv).decode(),
        "tag": base64.b64encode(tag).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    if extra:
        out.update(extra)
    return out


def _encrypt_with_node_secret(row: dict, secret: str, version: int | None = None) -> dict:
    key = hashlib.sha256((_PREFIX + secret).encode("utf-8")).digest()
    return _encrypt_with_key(row, key, {"secret_version": version} if version else {})


def _encrypt_with_hub_key(row: dict, public_pem: str) -> dict:
    key = os.urandom(32)
    public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    wrapped = public_key.encrypt(
        key,
        OAEP(mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    out = _encrypt_with_key(row, key)
    out["hub_key_envelope"] = {
        "algorithm": "rsa-oaep-sha256",
        "key_id": "test-key",
        "wrapped_key": base64.b64encode(wrapped).decode(),
    }
    return out


def _rsa_pair() -> tuple[str, str]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return public_pem, private_pem


def _trace_row(req_id: str, task: str = "x") -> dict:
    return {
        "prism_compatible": True,
        "requestId": req_id,
        "sessionId": "s_" + req_id,
        "path": "/v1/responses",
        "upstream": "openai",
        "requestBody": json.dumps({"model": "gpt-test", "input": task}),
        "responseBody": json.dumps({"id": "resp_" + req_id}),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------
def test_fails_closed_without_node_secret(tmp_path: Path) -> None:
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [{"encrypted": True, "iv": "bad", "tag": "bad", "ciphertext": "bad"}])
    with pytest.raises(TraceDecryptError, match="cannot be exported without node secret"):
        read_trace_rows_detailed(inp, node_secret="")


def test_fails_closed_on_bad_ciphertext(tmp_path: Path) -> None:
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [{"encrypted": True, "iv": "bad", "tag": "bad", "ciphertext": "bad"}])
    with pytest.raises(TraceDecryptError, match="failed to decrypt encrypted trace row"):
        read_trace_rows_detailed(inp, node_secret="0" * 64)


# ---------------------------------------------------------------------------
# Node-secret + keyring
# ---------------------------------------------------------------------------
def test_decrypts_node_secret_rows(tmp_path: Path) -> None:
    secret = "a" * 64
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [_encrypt_with_node_secret(_trace_row("req_plain"), secret)])
    result = read_trace_rows_detailed(inp, node_secret=secret)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["requestId"] == "req_plain"
    assert result["stats"]["encrypted_rows"] == 1
    assert result["stats"]["decrypt_failures"] == 0


def test_secret_version_selects_keyring_entry_before_fallback(tmp_path: Path) -> None:
    fallback = "a" * 64
    rotated = "b" * 64
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(
        inp,
        [
            _encrypt_with_node_secret(_trace_row("req_rotated"), rotated, 2),
            _encrypt_with_node_secret(_trace_row("req_fallback"), fallback),
        ],
    )
    result = read_trace_rows_detailed(inp, node_secret=fallback, node_secret_keyring={2: rotated})
    assert [r["requestId"] for r in result["rows"]] == ["req_rotated", "req_fallback"]
    assert result["stats"]["decrypt_failures"] == 0


def test_keyring_miss_falls_back_to_node_secret(tmp_path: Path) -> None:
    current = "b" * 64
    inp = tmp_path / "traces.jsonl"
    # encrypted with current secret but claims version 2 (stale keyring entry missing)
    _write_jsonl(inp, [_encrypt_with_node_secret(_trace_row("req_fb"), current, 2)])
    # keyring has version 2 = a DIFFERENT (wrong) secret; node_secret = current must save it
    result = read_trace_rows_detailed(inp, node_secret=current, node_secret_keyring={2: "z" * 64})
    assert result["rows"][0]["requestId"] == "req_fb"


# ---------------------------------------------------------------------------
# Hub-key envelope
# ---------------------------------------------------------------------------
def test_decrypts_hub_key_envelope_with_private_key(tmp_path: Path) -> None:
    public_pem, private_pem = _rsa_pair()
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [_encrypt_with_hub_key(_trace_row("req_hub"), public_pem)])
    result = read_trace_rows_detailed(inp, hub_private_key=private_pem)
    assert result["rows"][0]["requestId"] == "req_hub"
    assert result["stats"]["decrypt_failures"] == 0


def test_hub_wrong_key_fails_closed_with_hub_message(tmp_path: Path) -> None:
    public_pem, _ = _rsa_pair()
    _, wrong_pem = _rsa_pair()
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [_encrypt_with_hub_key(_trace_row("req_hub2"), public_pem)])
    with pytest.raises(TraceDecryptError, match="with hub private key"):
        read_trace_rows_detailed(inp, hub_private_key=wrong_pem)


def test_hub_wrong_key_falls_back_to_node_secret(tmp_path: Path) -> None:
    # Row encrypted with node secret (secret_version=7) but carrying a hub
    # envelope from a DIFFERENT public key the provided private key can't match.
    public_pem, _ = _rsa_pair()
    _, wrong_pem = _rsa_pair()
    node_secret = "c" * 64
    row = _encrypt_with_node_secret(_trace_row("req_fb_hub"), node_secret, 7)
    row["hub_key_envelope"] = _encrypt_with_hub_key({"x": 1}, public_pem)["hub_key_envelope"]
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(inp, [row])
    result = read_trace_rows_detailed(
        inp,
        hub_private_key=wrong_pem,
        node_secret=node_secret,
        node_secret_keyring={7: node_secret},
    )
    assert result["rows"][0]["requestId"] == "req_fb_hub"
    assert result["stats"]["decrypt_failures"] == 0


# ---------------------------------------------------------------------------
# allow-partial
# ---------------------------------------------------------------------------
def test_allow_partial_skips_undecryptable_keeps_plaintext(tmp_path: Path) -> None:
    good_secret = "a" * 64
    inp = tmp_path / "traces.jsonl"
    _write_jsonl(
        inp,
        [
            _trace_row("plaintext"),  # plaintext passes through
            _encrypt_with_node_secret(_trace_row("good"), good_secret),
            {"encrypted": True, "iv": "bad", "tag": "bad", "ciphertext": "bad"},  # undecryptable
        ],
    )
    result = read_trace_rows_detailed(inp, node_secret=good_secret, allow_partial=True)
    ids = [r["requestId"] for r in result["rows"]]
    assert "plaintext" in ids and "good" in ids
    assert result["stats"]["decrypt_failures"] == 1
    assert result["stats"]["encrypted_rows"] == 2


def test_derive_node_key_matches_proxy_writer() -> None:
    assert derive_node_key("abc") == hashlib.sha256((_PREFIX + "abc").encode()).digest()
