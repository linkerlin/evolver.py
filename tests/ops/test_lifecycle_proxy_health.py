"""Sprint 14.7 — ops lifecycle proxy health (Node lifecycleProxyHealth)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops import lifecycle
from evolver.proxy.server import settings as proxy_settings


@pytest.fixture(autouse=True)
def _reset_table() -> None:
    lifecycle._reset_process_table_for_test()
    yield
    lifecycle._reset_process_table_for_test()


@pytest.fixture
def settings_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "proxy-settings.json"
    monkeypatch.setenv("EVOLVER_PROXY_SETTINGS_PATH", str(path))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path / "repo"))
    (tmp_path / "repo").mkdir()
    (tmp_path / "ws").mkdir()
    return tmp_path


class TestExpectsProxy:
    def test_loopback_auto_injected(self, settings_dir: Path) -> None:
        env = {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:19820",
            "EVOMAP_PROXY_AUTO_INJECTED": "1",
        }
        assert lifecycle.expects_proxy(env) is True
        assert lifecycle.prepare_start_env(env)["EVOMAP_PROXY"] == "1"

    def test_codex_loopback_provider(self, settings_dir: Path, tmp_path: Path) -> None:
        codex = tmp_path / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text(
            "\n".join(
                [
                    'model_provider = "evomap-proxy"',
                    "",
                    "[model_providers.evomap-proxy]",
                    'name = "EvoMap Proxy"',
                    'base_url = "http://127.0.0.1:19820/v1"',
                    'wire_api = "responses"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        assert lifecycle.expects_proxy({"HOME": str(tmp_path)}) is True


class TestProxyHealth:
    def test_stale_pid_unhealthy(self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:19820",
                    "token": "test-token",
                    "pid": 42424242,
                }
            }
        )
        health = lifecycle.check_proxy_health(
            {"ANTHROPIC_BASE_URL": "http://127.0.0.1:19820", "EVOMAP_PROXY_AUTO_INJECTED": "1"}
        )
        assert health["healthy"] is False
        assert health["reason"] == "proxy_pid_stale"
        assert health["proxyPid"] == 42424242

    def test_should_restart_when_proxy_unhealthy_and_loop_live(self, settings_dir: Path) -> None:
        proxy_settings.save_settings(
            {
                "proxy": {
                    "url": "http://127.0.0.1:19820",
                    "token": "test-token",
                    "pid": 42424242,
                }
            }
        )
        assert (
            lifecycle.should_restart_for_proxy(
                [1],  # pretend a loop is live
                {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:19820",
                    "EVOMAP_PROXY_AUTO_INJECTED": "1",
                },
            )
            is True
        )


class TestOwnedLoops:
    def test_unrelated_absolute_not_owned(
        self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        repo = Path(os.environ.get("EVOLVER_REPO_ROOT") or settings_dir / "repo")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        lifecycle._set_process_table_for_test(
            [
                {
                    "pid": 990001,
                    "args": "node /tmp/other-evolver/index.js --loop",
                    "cwd": "/tmp/other-evolver",
                }
            ]
        )
        assert lifecycle.get_owned_loop_pids([990001]) == []
        assert lifecycle.stop_owned_loops().status == "not_running"

    def test_relative_from_repo_cwd_owned(
        self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = Path(settings_dir / "repo").resolve()
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
        lifecycle._set_process_table_for_test(
            [
                {
                    "pid": 990002,
                    "args": "node index.js --loop",
                    "cwd": str(repo),
                }
            ]
        )
        assert lifecycle.get_owned_loop_pids([990002]) == [990002]

    def test_relative_from_other_cwd_not_owned(
        self, settings_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = Path(settings_dir / "repo").resolve()
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        lifecycle._set_process_table_for_test(
            [
                {
                    "pid": 990003,
                    "args": "node index.js --loop",
                    "cwd": "/tmp/other-evolver-relative",
                }
            ]
        )
        assert lifecycle.get_owned_loop_pids([990003]) == []

    def test_is_current_loop_command(self, settings_dir: Path) -> None:
        repo = Path(settings_dir / "repo").resolve()
        assert (
            lifecycle.is_current_loop_command(f"node {repo / 'index.js'} --loop", repo_root=repo)
            is True
        )
        assert (
            lifecycle.is_current_loop_command("node /tmp/other/index.js --loop", repo_root=repo)
            is False
        )
