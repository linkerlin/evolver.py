"""Tests for evolver.adapters.kiro."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.adapters import kiro


class TestBuildHookConfig:
    def test_session_start(self) -> None:
        cfg = kiro.build_hook_config("session_start", ".kiro/hooks")
        assert cfg["name"] == "Evolver Session Start"
        assert cfg["when"]["type"] == "promptSubmit"
        assert cfg["_evolver_managed"] is True

    def test_signal_detect(self) -> None:
        cfg = kiro.build_hook_config("signal_detect", ".kiro/hooks")
        assert cfg["name"] == "Evolver Signal Detect"
        assert cfg["when"]["type"] == "postToolUse"
        assert "write" in cfg["when"]["toolTypes"]

    def test_session_end(self) -> None:
        cfg = kiro.build_hook_config("session_end", ".kiro/hooks")
        assert cfg["name"] == "Evolver Session End"
        assert cfg["when"]["type"] == "agentStop"

    def test_commands_use_python(self) -> None:
        for kind in ("session_start", "signal_detect", "session_end"):
            cfg = kiro.build_hook_config(kind, ".kiro/hooks")
            assert "python" in cfg["then"]["command"].lower()

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(KeyError):
            kiro.build_hook_config("invalid", ".kiro/hooks")


class TestIsEvolverManagedHookFile:
    def test_by_marker(self, tmp_path: Path) -> None:
        p = tmp_path / "test.kiro.hook"
        p.write_text(json.dumps({"_evolver_managed": True}), encoding="utf-8")
        assert kiro._is_evolver_managed_hook_file(p) is True

    def test_by_name(self, tmp_path: Path) -> None:
        p = tmp_path / "test.kiro.hook"
        p.write_text(json.dumps({"name": "Evolver Something"}), encoding="utf-8")
        assert kiro._is_evolver_managed_hook_file(p) is True

    def test_by_command(self, tmp_path: Path) -> None:
        p = tmp_path / "test.kiro.hook"
        p.write_text(
            json.dumps({"then": {"command": "run evolver-session-start.py"}}),
            encoding="utf-8",
        )
        assert kiro._is_evolver_managed_hook_file(p) is True

    def test_non_managed(self, tmp_path: Path) -> None:
        p = tmp_path / "test.kiro.hook"
        p.write_text(json.dumps({"name": "Custom Hook"}), encoding="utf-8")
        assert kiro._is_evolver_managed_hook_file(p) is False

    def test_missing_file(self, tmp_path: Path) -> None:
        assert kiro._is_evolver_managed_hook_file(tmp_path / "missing.kiro.hook") is False


class TestInstall:
    def test_writes_hook_files(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        result = kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["ok"] is True
        hooks_dir = config_root / ".kiro" / "hooks"
        for name in kiro.HOOK_FILES.values():
            assert (hooks_dir / name).exists()

    def test_skips_when_installed(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["skipped"] is True

    def test_force_overwrites(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = kiro.install(config_root=config_root, evolver_root=evolver_root, force=True)
        assert result.get("skipped") is not True

    def test_injects_agents_md(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        agents_md = config_root / "AGENTS.md"
        assert agents_md.exists()
        assert "evolver-evolution-memory" in agents_md.read_text(encoding="utf-8")


class TestUninstall:
    def test_removes_hooks(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        kiro.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = kiro.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["removed"] is True

    def test_no_hooks_found(self, tmp_path: Path) -> None:
        result = kiro.uninstall(config_root=tmp_path / "project", evolver_root=tmp_path)
        assert result["removed"] is False

    def test_preserves_user_hooks(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        hooks_dir = config_root / ".kiro" / "hooks"
        hooks_dir.mkdir(parents=True)
        user_hook = hooks_dir / "custom.kiro.hook"
        user_hook.write_text(json.dumps({"name": "Custom"}), encoding="utf-8")
        evolver_hook = hooks_dir / "evolver-session-start.kiro.hook"
        evolver_hook.write_text(json.dumps({"_evolver_managed": True}), encoding="utf-8")

        result = kiro.uninstall(config_root=config_root, evolver_root=tmp_path)
        assert result["removed"] is True
        assert user_hook.exists()
        assert not evolver_hook.exists()
