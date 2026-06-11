"""Tests for evolver.gep.crypto."""

from __future__ import annotations

import pytest

from evolver.gep.crypto import (
    decrypt,
    encrypt,
    generate_key,
    pack,
    unpack,
)


class TestGenerateKey:
    def test_length(self):
        key = generate_key()
        assert len(key) == 32

    def test_random(self):
        assert generate_key() != generate_key()


class TestEncryptDecrypt:
    def test_roundtrip_bytes(self):
        key = generate_key()
        pt = b"hello world"
        ct = encrypt(pt, key)
        assert decrypt(ct, key) == pt

    def test_roundtrip_str(self):
        key = generate_key()
        pt = "hello world 中文"
        ct = encrypt(pt, key)
        assert decrypt(ct, key).decode("utf-8") == pt

    def test_wrong_key(self):
        key = generate_key()
        ct = encrypt(b"secret", key)
        with pytest.raises(Exception):
            decrypt(ct, generate_key())

    def test_bad_key_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            encrypt(b"x", b"short")
        with pytest.raises(ValueError, match="32 bytes"):
            decrypt(b"x", b"short")

    def test_ciphertext_too_short(self):
        key = generate_key()
        with pytest.raises(ValueError, match="too short"):
            decrypt(b"x", key)


class TestPackUnpack:
    def test_roundtrip(self):
        key = generate_key()
        packed = pack("hello", key)
        assert isinstance(packed, str)
        assert unpack(packed, key) == "hello"
