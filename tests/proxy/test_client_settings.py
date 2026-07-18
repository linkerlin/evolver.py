"""Tests for evolver.proxy.client_settings.

Ports the clientSettings contract scenarios from Node's
``proxyTokenReuse.test.js`` (token recovery, upstream credential
preservation, unsafe-path refusal, corrupt-file backup).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.proxy.client_settings import (
    MANAGED_BY,
    get_claude_settings_file,
    is_loopback_proxy_url,
    is_valid_reusable_proxy_token,
    read_reusable_client_proxy_token,
    sync_claude_proxy_settings,
)


def _fake_hex_token(seed: str) -> str:
    return (seed * 64)[:64]


def _write_settings(file: Path, payload: dict[str, Any]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_settings(file: Path) -> dict[str, Any]:
    return json.loads(file.read_text(encoding="utf-8"))


PROXY_URL = "http://127.0.0.1:39830"
TOKEN = _fake_hex_token("a")


class TestTokenValidation:
    def test_accepts_64_char_hex(self) -> None:
        assert is_valid_reusable_proxy_token("a" * 64)
        assert is_valid_reusable_proxy_token("0123456789abcdef" * 4)
        assert is_valid_reusable_proxy_token("A" * 64)

    def test_rejects_non_hex_or_wrong_length(self) -> None:
        assert not is_valid_reusable_proxy_token("a" * 63)
        assert not is_valid_reusable_proxy_token("g" * 64)
        assert not is_valid_reusable_proxy_token("")
        assert not is_valid_reusable_proxy_token(None)
        assert not is_valid_reusable_proxy_token(12345)


class TestLoopbackUrl:
    def test_accepts_loopback_http(self) -> None:
        assert is_loopback_proxy_url("http://127.0.0.1:8081")
        assert is_loopback_proxy_url("http://localhost:8081/")
        assert is_loopback_proxy_url("http://[::1]:8081")

    def test_rejects_non_loopback_or_https(self) -> None:
        assert not is_loopback_proxy_url("https://127.0.0.1:8081")
        assert not is_loopback_proxy_url("http://evomap.ai")
        assert not is_loopback_proxy_url("")
        assert not is_loopback_proxy_url(None)


class TestDefaultSettingsPath:
    def test_default_under_home(self) -> None:
        file = get_claude_settings_file({"HOME": "/home/tester"})
        assert file == Path("/home/tester") / ".claude" / "settings.json"

    def test_none_without_home(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: Path("")))
        assert get_claude_settings_file({"HOME": "", "USERPROFILE": ""}) is None


class TestReadReusableToken:
    def test_recovers_token_from_managed_settings(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) == TOKEN

    def test_rejects_unmarked_loopback_settings(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {"env": {"ANTHROPIC_BASE_URL": PROXY_URL, "ANTHROPIC_AUTH_TOKEN": TOKEN}},
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) is None

    def test_recovers_token_from_auto_injected_settings(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                    "EVOMAP_PROXY_AUTO_INJECTED": "1",
                }
            },
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) == TOKEN

    def test_recovers_token_from_evomap_proxy_url_loopback(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                    "EVOMAP_PROXY_URL": PROXY_URL,
                }
            },
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) == TOKEN

    def test_rejects_non_loopback_base_url(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://evomap.ai",
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) is None

    def test_rejects_invalid_token_shape(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": "not-a-hex-token",
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        assert read_reusable_client_proxy_token({"file": file, "env": {}}) is None

    def test_disabled_by_env(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        env = {"EVOMAP_PROXY_AUTO_INJECT": "off"}
        assert read_reusable_client_proxy_token({"file": file, "env": env}) is None

    def test_env_path_diverging_from_default_is_unsafe(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        workspace_file = tmp_path / "workspace" / ".claude" / "settings.json"
        _write_settings(
            workspace_file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                    "EVOMAP_PROXY_URL": PROXY_URL,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        env = {"HOME": str(home), "CLAUDE_SETTINGS_FILE": str(workspace_file)}
        assert read_reusable_client_proxy_token({"env": env}) is None

    def test_env_path_equal_to_default_is_allowed(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        default_file = home / ".claude" / "settings.json"
        _write_settings(
            default_file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": PROXY_URL,
                    "ANTHROPIC_AUTH_TOKEN": TOKEN,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        env = {"HOME": str(home), "CLAUDE_SETTINGS_FILE": str(default_file)}
        assert read_reusable_client_proxy_token({"env": env}) == TOKEN


class TestSyncClaudeProxySettings:
    def test_fresh_sync_writes_managed_settings(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": TOKEN, "file": file, "env": {}}
        )
        assert result["synced"] is True
        assert result["changed"] is True
        settings = _read_settings(file)
        assert settings["env"]["ANTHROPIC_BASE_URL"] == PROXY_URL
        assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert settings["env"]["CUSTOM_API_KEY"] == TOKEN
        assert settings["env"]["EVOMAP_PROXY_URL"] == PROXY_URL
        assert settings["env"]["EVOMAP_PROXY_AUTO_INJECTED"] == "1"
        assert settings["_evomap_proxy_client_env"]["managed_by"] == MANAGED_BY

    def test_second_sync_is_idempotent(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        info = {"url": PROXY_URL, "token": TOKEN, "file": file, "env": {}}
        sync_claude_proxy_settings(info)
        result = sync_claude_proxy_settings(info)
        assert result["synced"] is True
        assert result["changed"] is False

    def test_preserves_upstream_credentials(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://sub2api-api.evomap.work",
                    "ANTHROPIC_AUTH_TOKEN": "upstream-token",
                    "ANTHROPIC_API_KEY": "sk-upstream-api-key",
                }
            },
        )
        runtime_env: dict[str, str] = {}
        result = sync_claude_proxy_settings(
            {
                "url": PROXY_URL,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        assert result["synced"] is True
        settings = _read_settings(file)
        cfg = settings["env"]
        assert cfg["ANTHROPIC_BASE_URL"] == PROXY_URL
        assert cfg["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert cfg["CUSTOM_API_KEY"] == TOKEN
        assert cfg["EVOMAP_PROXY_URL"] == PROXY_URL
        assert cfg["EVOMAP_PROXY_AUTO_INJECTED"] == "1"
        assert cfg["EVOMAP_ANTHROPIC_BASE_URL"] == "https://sub2api-api.evomap.work"
        assert cfg["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "upstream-token"
        assert cfg["EVOMAP_ANTHROPIC_API_KEY"] == "sk-upstream-api-key"
        assert "ANTHROPIC_API_KEY" not in cfg
        assert settings["_evomap_proxy_client_env"]["managed_by"] == MANAGED_BY
        assert runtime_env["EVOMAP_ANTHROPIC_BASE_URL"] == "https://sub2api-api.evomap.work"
        assert runtime_env["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "upstream-token"
        assert runtime_env["EVOMAP_ANTHROPIC_API_KEY"] == "sk-upstream-api-key"
        assert runtime_env["EVOMAP_PROXY_AUTO_INJECTED"] == "1"
        assert "ANTHROPIC_BASE_URL" not in runtime_env
        assert "ANTHROPIC_AUTH_TOKEN" not in runtime_env

    def test_preserves_unmarked_loopback_upstream_credentials(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:19888",
                    "ANTHROPIC_AUTH_TOKEN": "local-upstream-token",
                }
            },
        )
        runtime_env: dict[str, str] = {}
        sync_claude_proxy_settings(
            {
                "url": "http://127.0.0.1:19820",
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        cfg = _read_settings(file)["env"]
        assert cfg["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19820"
        assert cfg["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert cfg["EVOMAP_ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19888"
        assert cfg["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "local-upstream-token"
        assert runtime_env["EVOMAP_ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19888"
        assert runtime_env["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "local-upstream-token"

    def test_does_not_overwrite_runtime_upstream_credentials(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://settings-upstream.example",
                    "ANTHROPIC_AUTH_TOKEN": "settings-upstream-token",
                    "ANTHROPIC_API_KEY": "sk-settings-upstream",
                }
            },
        )
        runtime_env = {
            "EVOMAP_ANTHROPIC_BASE_URL": "https://runtime-upstream.example",
            "EVOMAP_ANTHROPIC_AUTH_TOKEN": "runtime-upstream-token",
            "EVOMAP_ANTHROPIC_API_KEY": "sk-runtime-upstream",
        }
        sync_claude_proxy_settings(
            {
                "url": PROXY_URL,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        cfg = _read_settings(file)["env"]
        assert cfg["EVOMAP_ANTHROPIC_BASE_URL"] == "https://settings-upstream.example"
        assert cfg["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "settings-upstream-token"
        assert cfg["EVOMAP_ANTHROPIC_API_KEY"] == "sk-settings-upstream"
        assert runtime_env["EVOMAP_ANTHROPIC_BASE_URL"] == "https://runtime-upstream.example"
        assert runtime_env["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "runtime-upstream-token"
        assert runtime_env["EVOMAP_ANTHROPIC_API_KEY"] == "sk-runtime-upstream"

    def test_does_not_mix_runtime_base_with_settings_credentials(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://settings-upstream.example",
                    "ANTHROPIC_AUTH_TOKEN": "settings-upstream-token",
                    "ANTHROPIC_API_KEY": "sk-settings-upstream",
                }
            },
        )
        runtime_env = {"EVOMAP_ANTHROPIC_BASE_URL": "https://runtime-upstream.example"}
        sync_claude_proxy_settings(
            {
                "url": PROXY_URL,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        cfg = _read_settings(file)["env"]
        assert cfg["EVOMAP_ANTHROPIC_BASE_URL"] == "https://settings-upstream.example"
        assert cfg["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "settings-upstream-token"
        assert cfg["EVOMAP_ANTHROPIC_API_KEY"] == "sk-settings-upstream"
        assert runtime_env["EVOMAP_ANTHROPIC_BASE_URL"] == "https://runtime-upstream.example"
        assert "EVOMAP_ANTHROPIC_AUTH_TOKEN" not in runtime_env
        assert "EVOMAP_ANTHROPIC_API_KEY" not in runtime_env
        assert "EVOMAP_PROXY_AUTO_INJECTED" not in runtime_env

    def test_keeps_stored_loopback_upstream_when_already_managed(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        proxy_url = "http://127.0.0.1:19820"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": proxy_url,
                    "ANTHROPIC_AUTH_TOKEN": _fake_hex_token("6f"),
                    "EVOMAP_PROXY_AUTO_INJECTED": "1",
                    "EVOMAP_PROXY_URL": proxy_url,
                    "EVOMAP_ANTHROPIC_BASE_URL": "http://127.0.0.1:19888",
                    "EVOMAP_ANTHROPIC_AUTH_TOKEN": "local-upstream-token",
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        runtime_env: dict[str, str] = {}
        sync_claude_proxy_settings(
            {
                "url": proxy_url,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        assert runtime_env["EVOMAP_ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19888"
        assert runtime_env["EVOMAP_ANTHROPIC_AUTH_TOKEN"] == "local-upstream-token"

    def test_removes_managed_stale_proxy_token_residual(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        stale = _fake_hex_token("5e")
        old_url = "http://127.0.0.1:39700"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": old_url,
                    "ANTHROPIC_AUTH_TOKEN": stale,
                    "EVOMAP_PROXY_AUTO_INJECTED": "1",
                    "EVOMAP_PROXY_URL": old_url,
                    "EVOMAP_ANTHROPIC_BASE_URL": old_url,
                    "EVOMAP_ANTHROPIC_AUTH_TOKEN": stale,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        runtime_env: dict[str, str] = {}
        new_url = "http://127.0.0.1:39841"
        sync_claude_proxy_settings(
            {
                "url": new_url,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        cfg = _read_settings(file)["env"]
        assert cfg["ANTHROPIC_BASE_URL"] == new_url
        assert cfg["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert "EVOMAP_ANTHROPIC_BASE_URL" not in cfg
        assert "EVOMAP_ANTHROPIC_AUTH_TOKEN" not in cfg
        assert "EVOMAP_ANTHROPIC_BASE_URL" not in runtime_env
        assert "EVOMAP_ANTHROPIC_AUTH_TOKEN" not in runtime_env

    def test_removes_managed_stale_proxy_api_key_residual(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        stale = _fake_hex_token("7a")
        old_url = "http://127.0.0.1:39710"
        _write_settings(
            file,
            {
                "env": {
                    "ANTHROPIC_BASE_URL": old_url,
                    "ANTHROPIC_AUTH_TOKEN": stale,
                    "EVOMAP_PROXY_AUTO_INJECTED": "1",
                    "EVOMAP_PROXY_URL": old_url,
                    "EVOMAP_ANTHROPIC_BASE_URL": old_url,
                    "EVOMAP_ANTHROPIC_API_KEY": stale,
                },
                "_evomap_proxy_client_env": {"managed_by": MANAGED_BY},
            },
        )
        runtime_env: dict[str, str] = {}
        new_url = "http://127.0.0.1:39850"
        sync_claude_proxy_settings(
            {
                "url": new_url,
                "token": TOKEN,
                "file": file,
                "env": {},
                "runtime_env": runtime_env,
            }
        )
        cfg = _read_settings(file)["env"]
        assert cfg["ANTHROPIC_BASE_URL"] == new_url
        assert cfg["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert "EVOMAP_ANTHROPIC_BASE_URL" not in cfg
        assert "EVOMAP_ANTHROPIC_API_KEY" not in cfg
        assert "EVOMAP_ANTHROPIC_BASE_URL" not in runtime_env
        assert "EVOMAP_ANTHROPIC_API_KEY" not in runtime_env

    def test_does_not_overwrite_corrupt_settings_but_backs_up(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        corrupt = '{ "env": { "ANTHROPIC_BASE_URL": '
        file.write_text(corrupt, encoding="utf-8")
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": TOKEN, "file": file, "env": {}}
        )
        assert result["synced"] is False
        assert result["reason"] == "invalid_settings_json"
        assert file.read_text(encoding="utf-8") == corrupt
        backups = [
            entry
            for entry in (tmp_path / "backups").iterdir()
            if entry.name.startswith("settings.json.pre-evomap-proxy-sync-")
        ]
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == corrupt

    def test_backup_written_before_rewrite(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        original = {"env": {"OTHER": "keep"}}
        _write_settings(file, original)
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": TOKEN, "file": file, "env": {}}
        )
        assert result["changed"] is True
        assert result["backupFile"] is not None
        assert json.loads(Path(result["backupFile"]).read_text(encoding="utf-8")) == original
        assert _read_settings(file)["env"]["OTHER"] == "keep"

    def test_backup_disabled_by_flag(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        _write_settings(file, {"env": {}})
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": TOKEN, "file": file, "env": {}, "backup": False}
        )
        assert result["changed"] is True
        assert result["backupFile"] is None
        assert not (tmp_path / "backups").exists()

    def test_disabled_by_env(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        result = sync_claude_proxy_settings(
            {
                "url": PROXY_URL,
                "token": TOKEN,
                "file": file,
                "env": {"EVOMAP_PROXY_AUTO_INJECT": "0"},
            }
        )
        assert result == {"synced": False, "reason": "disabled"}
        assert not file.exists()

    def test_missing_proxy_settings(self, tmp_path: Path) -> None:
        file = tmp_path / "settings.json"
        result = sync_claude_proxy_settings({"url": "", "token": TOKEN, "file": file, "env": {}})
        assert result == {"synced": False, "reason": "missing_proxy_settings"}
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": "short", "file": file, "env": {}}
        )
        assert result == {"synced": False, "reason": "missing_proxy_settings"}

    def test_unsafe_env_settings_path_refused(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        workspace_file = tmp_path / "workspace" / ".claude" / "settings.json"
        _write_settings(workspace_file, {"env": {}})
        before = workspace_file.read_text(encoding="utf-8")
        result = sync_claude_proxy_settings(
            {
                "url": PROXY_URL,
                "token": TOKEN,
                "env": {"HOME": str(home), "CLAUDE_SETTINGS_FILE": str(workspace_file)},
            }
        )
        assert result["synced"] is False
        assert result["reason"] == "unsafe_settings_path"
        assert workspace_file.read_text(encoding="utf-8") == before

    def test_syncs_default_home_settings_without_env_override(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        result = sync_claude_proxy_settings(
            {"url": PROXY_URL, "token": TOKEN, "env": {"HOME": str(home)}}
        )
        assert result["synced"] is True
        settings = _read_settings(home / ".claude" / "settings.json")
        assert settings["env"]["ANTHROPIC_BASE_URL"] == PROXY_URL
        assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == TOKEN
        assert settings["_evomap_proxy_client_env"]["managed_by"] == MANAGED_BY
