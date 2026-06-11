"""Tests for evolver.adapters.codex."""

from __future__ import annotations

from pathlib import Path

from evolver.adapters import codex


class TestBuildHooksJson:
    def test_structure(self, tmp_path: Path) -> None:
        hooks = codex.build_hooks_json(tmp_path)
        assert "hooks" in hooks
        for event in ("SessionStart", "PostToolUse", "Stop"):
            assert event in hooks["hooks"]

    def test_commands_use_python(self, tmp_path: Path) -> None:
        hooks = codex.build_hooks_json(tmp_path)
        for entries in hooks["hooks"].values():
            for h in entries:
                assert "python" in h["command"].lower()


class TestEnsureConfigToml:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        assert codex._ensure_config_toml(codex_dir) is True
        toml = codex_dir / "config.toml"
        assert toml.exists()
        assert "codex_hooks = true" in toml.read_text(encoding="utf-8")

    def test_idempotent(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        codex._ensure_config_toml(codex_dir)
        assert codex._ensure_config_toml(codex_dir) is False

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        toml = codex_dir / "config.toml"
        toml.write_text("[editor]\nfont_size = 14\n", encoding="utf-8")
        assert codex._ensure_config_toml(codex_dir) is True
        text = toml.read_text(encoding="utf-8")
        assert "[features]" in text
        assert "codex_hooks = true" in text
        assert "[editor]" in text


class TestCleanConfigToml:
    def test_removes_flag(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        toml = codex_dir / "config.toml"
        toml.write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
        assert codex._clean_config_toml(codex_dir) is True
        text = toml.read_text(encoding="utf-8")
        assert "codex_hooks" not in text

    def test_drops_empty_features(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        toml = codex_dir / "config.toml"
        toml.write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
        codex._clean_config_toml(codex_dir)
        assert "[features]" not in toml.read_text(encoding="utf-8")

    def test_noop_when_missing(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        assert codex._clean_config_toml(codex_dir) is False


class TestInstall:
    def test_creates_hooks_json(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        result = codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["ok"] is True
        assert (config_root / ".codex" / "hooks.json").exists()

    def test_creates_config_toml(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        toml = config_root / ".codex" / "config.toml"
        assert toml.exists()
        assert "codex_hooks = true" in toml.read_text(encoding="utf-8")

    def test_skips_when_installed(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["skipped"] is True


class TestUninstall:
    def test_removes_hooks(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = codex.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["removed"] is True

    def test_cleans_config_toml(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        codex.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = codex.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["removed"] is True
        toml = config_root / ".codex" / "config.toml"
        if toml.exists():
            assert "codex_hooks" not in toml.read_text(encoding="utf-8")

    def test_no_hooks_found(self, tmp_path: Path) -> None:
        result = codex.uninstall(config_root=tmp_path / "project", evolver_root=tmp_path)
        assert result["removed"] is False
