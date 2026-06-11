"""Tests for evolver.gep.privacy_client."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.privacy_client import decrypt, decrypt_file, encrypt, encrypt_file


class TestEncryptDecrypt:
    def test_passthrough_when_no_passphrase(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EVOLVER_PRIVACY_PASSPHRASE", raising=False)
        assert encrypt(b"hello") is None
        assert decrypt(b"hello") is None

    def test_round_trip(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("EVOLVER_PRIVACY_PASSPHRASE", "test-secret-123")
        # Point key file to tmp so tests don't pollute home
        import evolver.gep.privacy_client as pc

        monkeypatch.setattr(pc, "KEY_FILE", tmp_path / "privacy-key")

        plaintext = b"sensitive data here"
        token = encrypt(plaintext)
        assert token is not None
        assert token != plaintext
        recovered = decrypt(token)
        assert recovered == plaintext

    def test_different_nonce_each_time(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("EVOLVER_PRIVACY_PASSPHRASE", "test-secret-123")
        import evolver.gep.privacy_client as pc

        monkeypatch.setattr(pc, "KEY_FILE", tmp_path / "privacy-key")

        t1 = encrypt(b"x")
        t2 = encrypt(b"x")
        assert t1 != t2


class TestEncryptDecryptFile:
    def test_passthrough_when_disabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.delenv("EVOLVER_PRIVACY_PASSPHRASE", raising=False)
        f = tmp_path / "data.txt"
        f.write_text("hello")
        assert encrypt_file(f) is False
        assert f.read_text() == "hello"

    def test_encrypt_decrypt_roundtrip(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("EVOLVER_PRIVACY_PASSPHRASE", "test-secret-123")
        import evolver.gep.privacy_client as pc

        monkeypatch.setattr(pc, "KEY_FILE", tmp_path / "privacy-key")

        f = tmp_path / "data.txt"
        f.write_text("secret content")
        assert encrypt_file(f) is True
        assert f.read_bytes() != b"secret content"  # now encrypted
        assert decrypt_file(f) is True
        assert f.read_text() == "secret content"
