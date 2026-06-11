"""Tests for evolver.gep.workspace_keychain."""

from __future__ import annotations

import pytest

from evolver.gep.workspace_keychain import (
    WorkspaceKeychain,
    _FallbackBackend,
    _derive_key,
)


class TestDeriveKey:
    def test_stable(self):
        k1 = _derive_key(b"pass", b"salt")
        k2 = _derive_key(b"pass", b"salt")
        assert k1 == k2
        assert len(k1) == 32

    def test_differs(self):
        k1 = _derive_key(b"pass", b"salt")
        k2 = _derive_key(b"pass", b"other")
        assert k1 != k2


class TestFallbackBackend:
    def test_roundtrip(self, tmp_path):
        fb = _FallbackBackend(path=tmp_path / "kc.json")
        fb.set("api_key", "secret123")
        assert fb.get("api_key") == "secret123"

    def test_delete(self, tmp_path):
        fb = _FallbackBackend(path=tmp_path / "kc.json")
        fb.set("x", "1")
        fb.delete("x")
        assert fb.get("x") is None

    def test_list_keys(self, tmp_path):
        fb = _FallbackBackend(path=tmp_path / "kc.json")
        fb.set("a", "1")
        fb.set("b", "2")
        assert sorted(fb.list_keys()) == ["a", "b"]

    def test_persistence(self, tmp_path):
        path = tmp_path / "kc.json"
        fb1 = _FallbackBackend(path=path)
        fb1.set("k", "v")
        fb2 = _FallbackBackend(path=path)
        assert fb2.get("k") == "v"

    def test_encryption(self, tmp_path):
        path = tmp_path / "kc.json"
        fb = _FallbackBackend(path=path)
        fb.set("secret", "value")
        raw = path.read_text(encoding="utf-8")
        # Should not contain plaintext secret
        assert "secret" not in raw or "value" not in raw


class TestWorkspaceKeychain:
    def test_set_get_delete(self, tmp_path, monkeypatch):
        # Force fallback so tests are deterministic across OS
        monkeypatch.setattr(
            "evolver.gep.workspace_keychain._KeyringBackend.available",
            lambda self: False,
        )
        kc = WorkspaceKeychain()
        kc._fb = _FallbackBackend(path=tmp_path / "kc.json")

        kc.set("token", "abc")
        assert kc.get("token") == "abc"
        kc.delete("token")
        assert kc.get("token") is None

    def test_clear(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "evolver.gep.workspace_keychain._KeyringBackend.available",
            lambda self: False,
        )
        kc = WorkspaceKeychain()
        kc._fb = _FallbackBackend(path=tmp_path / "kc.json")
        kc.set("a", "1")
        kc.set("b", "2")
        kc.clear()
        assert kc.list_keys() == []

    def test_list_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "evolver.gep.workspace_keychain._KeyringBackend.available",
            lambda self: False,
        )
        kc = WorkspaceKeychain()
        kc._fb = _FallbackBackend(path=tmp_path / "kc.json")
        kc.set("x", "1")
        assert kc.list_keys() == ["x"]
