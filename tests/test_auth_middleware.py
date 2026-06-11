"""Tests for evolver.ops.auth_middleware."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from evolver.ops.auth_middleware import (
    _auth_path,
    _extract_token,
    create_token,
    load_auth_db,
    require_role,
    revoke_token,
    save_auth_db,
    ws_require_role,
)


class TestAuthDb:
    def test_load_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        db = load_auth_db()
        assert db == {"tokens": {}}

    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        save_auth_db({"tokens": {"abc": {"role": "admin"}}})
        db = load_auth_db()
        assert db["tokens"]["abc"]["role"] == "admin"


class TestCreateToken:
    def test_create(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        token = create_token(role="admin")
        assert len(token) > 20
        db = load_auth_db()
        assert db["tokens"][token]["role"] == "admin"


class TestRevokeToken:
    def test_revoke(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        token = create_token()
        assert revoke_token(token) is True
        assert revoke_token(token) is False


class TestExtractToken:
    def test_bearer(self):
        class FakeReq:
            headers = {"authorization": "Bearer mytoken"}
        assert _extract_token(FakeReq()) == "mytoken"

    def test_missing(self):
        class FakeReq:
            headers = {}
        assert _extract_token(FakeReq()) is None


class TestRequireRole:
    def test_missing_token(self):
        class FakeReq:
            headers = {}
        with pytest.raises(HTTPException, match="401"):
            require_role(FakeReq())

    def test_invalid_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        class FakeReq:
            headers = {"authorization": "Bearer bad"}
        with pytest.raises(HTTPException, match="401"):
            require_role(FakeReq())

    def test_insufficient_role(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        token = create_token(role="readonly")
        class FakeReq:
            headers = {"authorization": f"Bearer {token}"}
        with pytest.raises(HTTPException, match="403"):
            require_role(FakeReq(), min_role="admin")

    def test_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("evolver.ops.auth_middleware._auth_path", lambda: tmp_path / "auth.json")
        token = create_token(role="admin")
        class FakeReq:
            headers = {"authorization": f"Bearer {token}"}
        assert require_role(FakeReq(), min_role="admin") == token
