"""Sprint 15.2 — proxy token mint/reuse across daemon restarts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evolver.cli import main as cli_main
from evolver.proxy import token as tok
from evolver.proxy.client_settings import MANAGED_BY
from evolver.proxy.server import settings as proxy_settings
from evolver.proxy.server.routes import router


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings_path = tmp_path / "proxy-settings.json"
    monkeypatch.setenv("EVOLVER_PROXY_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("EVOMAP_PROXY_TOKEN", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return tmp_path


class TestMintAndValidate:
    def test_mint_is_64_hex(self) -> None:
        t = tok.mint_proxy_token()
        assert len(t) == 64
        assert all(c in "0123456789abcdef" for c in t)


class TestStalePid:
    def test_dead_pid_is_stale(self) -> None:
        assert tok.is_proxy_pid_stale(999_999_999) is True

    def test_live_pid_not_stale(self) -> None:
        assert tok.is_proxy_pid_stale(os.getpid()) is False


class TestResolveReuse:
    def test_mints_when_no_settings(self, isolated_settings: Path) -> None:
        _ = isolated_settings
        info = tok.resolve_proxy_token(port=18081, sync_client=False)
        assert info["source"] == "mint"
        assert info["reused"] is False
        assert len(info["token"]) == 64
        settings = proxy_settings.load_settings()
        assert settings["proxy"]["token"] == info["token"]
        assert settings["proxy"]["pid"] == os.getpid()

    def test_reuses_settings_token_even_if_pid_stale(self, isolated_settings: Path) -> None:
        _ = isolated_settings
        old = "a" * 64
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:18082",
                    "pid": 999_999_999,
                    "started_at": "2020-01-01T00:00:00Z",
                    "token": old,
                }
            }
        )
        info = tok.resolve_proxy_token(port=18082, sync_client=False)
        assert info["token"] == old
        assert info["source"] == "settings"
        assert info["reused"] is True
        assert info["stale_cleared"] is True
        # New block written with our live pid
        settings = proxy_settings.load_settings()
        assert settings["proxy"]["token"] == old
        assert settings["proxy"]["pid"] == os.getpid()

    def test_recovers_from_claude_client_settings(
        self, isolated_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_settings
        old = "1a" * 32
        claude = tmp_path / "claude" / "settings.json"
        claude.parent.mkdir(parents=True)
        claude.write_text(
            json.dumps(
                {
                    "env": {
                        "ANTHROPIC_BASE_URL": "http://127.0.0.1:18083",
                        "ANTHROPIC_AUTH_TOKEN": old,
                        "EVOMAP_ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                        "EVOMAP_ANTHROPIC_AUTH_TOKEN": "upstream-token",
                    },
                    "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_SETTINGS_FILE", str(claude))
        # No proxy block in settings
        info = tok.resolve_proxy_token(
            port=18083,
            sync_client=True,
            client_settings_opts={"file": claude},
        )
        assert info["token"] == old
        assert info["source"] == "client_settings"
        # Client settings still point at proxy with same token
        client = json.loads(claude.read_text(encoding="utf-8"))
        assert client["env"]["ANTHROPIC_AUTH_TOKEN"] == old
        assert client["env"]["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "upstream-token"

    def test_previous_tokens_accepted_for_auth(self, isolated_settings: Path) -> None:
        _ = isolated_settings
        grace = "b" * 64
        primary = "c" * 64
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:18084",
                    "pid": os.getpid(),
                    "token": primary,
                    "previous_tokens": [grace, 123, None, "not-hex"],
                }
            }
        )
        os.environ["EVOMAP_PROXY_TOKEN"] = primary
        assert tok.authorize_bearer(primary) is True
        assert tok.authorize_bearer(grace) is True
        assert tok.authorize_bearer("d" * 64) is False

    def test_preserves_previous_tokens_across_resolve(self, isolated_settings: Path) -> None:
        _ = isolated_settings
        grace = "e" * 64
        old = "f" * 64
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:18085",
                    "pid": 999_999_998,
                    "token": old,
                    "previous_tokens": [grace],
                }
            }
        )
        info = tok.resolve_proxy_token(port=18085, sync_client=False)
        assert info["token"] == old
        assert grace in info["previous_tokens"]
        settings = proxy_settings.load_settings()
        assert grace in settings["proxy"].get("previous_tokens", [])


class TestAuthIntegration:
    def test_require_auth_accepts_grace_token(
        self, isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_settings
        primary = "a" * 64
        grace = "b" * 64
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:18086",
                    "pid": os.getpid(),
                    "token": primary,
                    "previous_tokens": [grace],
                }
            }
        )
        monkeypatch.setenv("EVOMAP_PROXY_TOKEN", primary)
        app = FastAPI()
        app.include_router(router, prefix="/v1/a2a")
        client = TestClient(app)
        # Models endpoint needs auth
        res = client.get(
            "/v1/a2a/v1/models",
            headers={"Authorization": f"Bearer {grace}"},
        )
        assert res.status_code == 200

        res_bad = client.get(
            "/v1/a2a/v1/models",
            headers={"Authorization": f"Bearer {'0' * 64}"},
        )
        assert res_bad.status_code == 401


class TestCliProxyToken:
    def test_proxy_token_command(self, isolated_settings: Path) -> None:
        _ = isolated_settings
        code = cli_main(["proxy-token", "--port", "18087", "--no-sync-client"])
        assert code == 0
        settings = proxy_settings.load_settings()
        assert len(settings["proxy"]["token"]) == 64
