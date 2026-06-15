"""Tests for evolver.adapters.setup_hooks."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.adapters.setup_hooks import (
    ADAPTER_PLATFORMS,
    SUPPORTED_PLATFORMS,
    _detect_platform,
    install_hooks,
)


class TestDetectPlatform:
    def test_detect_cursor(self, tmp_path: Path) -> None:
        (tmp_path / ".cursor").mkdir()
        assert _detect_platform(tmp_path) == "cursor"

    def test_detect_claude(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        assert _detect_platform(tmp_path) == "claude-code"

    def test_detect_vscode(self, tmp_path: Path) -> None:
        (tmp_path / ".vscode").mkdir()
        assert _detect_platform(tmp_path) == "vscode"

    def test_detect_codex(self, tmp_path: Path) -> None:
        (tmp_path / ".codex").mkdir()
        assert _detect_platform(tmp_path) == "codex"

    def test_detect_kiro(self, tmp_path: Path) -> None:
        (tmp_path / ".kiro").mkdir()
        assert _detect_platform(tmp_path) == "kiro"

    def test_detect_opencode(self, tmp_path: Path) -> None:
        (tmp_path / ".opencode").mkdir()
        assert _detect_platform(tmp_path) == "opencode"

    def test_detect_none(self, tmp_path: Path) -> None:
        assert _detect_platform(tmp_path) is None

    def test_detect_priority_cursor_over_vscode(self, tmp_path: Path) -> None:
        (tmp_path / ".cursor").mkdir()
        (tmp_path / ".vscode").mkdir()
        assert _detect_platform(tmp_path) == "cursor"


class TestInstallHooks:
    def test_invalid_directory(self) -> None:
        result = install_hooks(project_dir="/nonexistent/path/12345")
        assert result["ok"] is False
        assert "Not a directory" in result["error"]

    def test_unsupported_platform(self, tmp_path: Path) -> None:
        result = install_hooks(platform="emacs", project_dir=tmp_path)
        assert result["ok"] is False
        assert "Unsupported platform" in result["error"]

    def test_auto_falls_back_to_generic(self, tmp_path: Path) -> None:
        result = install_hooks(platform="auto", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "generic"
        assert any("EVOLVER_HOOK.md" in m for m in result["messages"])

    def test_adapter_install_uses_project_dir_not_home(self, tmp_path: Path) -> None:
        """Hooks land under --project-dir even when ``~/.codex`` exists."""
        result = install_hooks(platform="codex", project_dir=tmp_path)
        assert result["ok"] is True
        assert (tmp_path / ".codex" / "hooks.json").exists()

    def test_cursor_adapter_install(self, tmp_path: Path) -> None:
        result = install_hooks(platform="cursor", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "cursor"
        hooks_json = tmp_path / ".cursor" / "hooks.json"
        assert hooks_json.exists()
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        assert "sessionStart" in data.get("hooks", {})
        assert (tmp_path / ".cursor" / "hooks" / "session_start.py").exists()

    def test_claude_code_adapter_install(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        result = install_hooks(platform="claude-code", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "claude-code"
        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "SessionStart" in data.get("hooks", {})
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        assert "Evolution Memory" in claude_md.read_text(encoding="utf-8")

    def test_vscode_hook(self, tmp_path: Path) -> None:
        result = install_hooks(platform="vscode", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "vscode"
        target = tmp_path / ".vscode" / "settings.json"
        assert target.exists()
        data = json.loads(target.read_text())
        assert data.get("python.analysis.typeCheckingMode") == "strict"
        assert data.get("editor.rulers") == [88, 120]

    def test_vscode_merges_existing(self, tmp_path: Path) -> None:
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        existing = vscode_dir / "settings.json"
        existing.write_text(json.dumps({"editor.tabSize": 4}), encoding="utf-8")
        result = install_hooks(platform="vscode", project_dir=tmp_path, force=True)
        assert result["ok"] is True
        data = json.loads(existing.read_text())
        assert data["editor.tabSize"] == 4
        assert data["python.analysis.typeCheckingMode"] == "strict"

    def test_generic_hook(self, tmp_path: Path) -> None:
        result = install_hooks(platform="generic", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "generic"
        target = tmp_path / "EVOLVER_HOOK.md"
        assert target.exists()
        content = target.read_text()
        assert "Integration Checklist" in content

    def test_skip_existing_without_force(self, tmp_path: Path) -> None:
        target = tmp_path / "EVOLVER_HOOK.md"
        target.write_text("existing", encoding="utf-8")
        result = install_hooks(platform="generic", project_dir=tmp_path)
        assert result["ok"] is True
        assert any("SKIP" in m for m in result["messages"])
        assert target.read_text() == "existing"

    def test_force_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "EVOLVER_HOOK.md"
        target.write_text("existing", encoding="utf-8")
        result = install_hooks(platform="generic", project_dir=tmp_path, force=True)
        assert result["ok"] is True
        assert any("OK" in m for m in result["messages"])
        assert "Integration Checklist" in target.read_text()

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        result = install_hooks(platform="cursor", project_dir=tmp_path, dry_run=True)
        assert result["ok"] is True
        assert not (tmp_path / ".cursor").exists()
        assert any("WOULD" in m for m in result["messages"])

    def test_codex_adapter_install(self, tmp_path: Path) -> None:
        result = install_hooks(platform="codex", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "codex"
        assert (tmp_path / ".codex" / "hooks.json").exists()
        assert (tmp_path / ".codex" / "config.toml").exists()

    def test_kiro_adapter_install(self, tmp_path: Path) -> None:
        result = install_hooks(platform="kiro", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "kiro"
        hooks_dir = tmp_path / ".kiro" / "hooks"
        assert hooks_dir.exists()
        assert any(hooks_dir.glob("*.kiro.hook"))

    def test_opencode_adapter_install(self, tmp_path: Path) -> None:
        result = install_hooks(platform="opencode", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "opencode"
        assert (tmp_path / ".opencode" / "plugins" / "evolver.js").exists()

    def test_codex_uninstall(self, tmp_path: Path) -> None:
        install_hooks(platform="codex", project_dir=tmp_path)
        result = install_hooks(platform="codex", project_dir=tmp_path, uninstall=True)
        assert result["ok"] is True

    def test_opencode_verify_after_install(self, tmp_path: Path) -> None:
        install_hooks(platform="opencode", project_dir=tmp_path)
        result = install_hooks(platform="opencode", project_dir=tmp_path, verify=True)
        assert result["ok"] is True
        assert any("plugin_file_present" in m for m in result["messages"])

    def test_cursor_uninstall(self, tmp_path: Path) -> None:
        (tmp_path / ".cursor").mkdir()
        install_hooks(platform="cursor", project_dir=tmp_path)
        result = install_hooks(platform="cursor", project_dir=tmp_path, uninstall=True)
        assert result["ok"] is True

    def test_uninstall_not_supported_for_vscode(self, tmp_path: Path) -> None:
        result = install_hooks(platform="vscode", project_dir=tmp_path, uninstall=True)
        assert result["ok"] is False
        assert "only supported" in result["error"]

    def test_adapter_dry_run(self, tmp_path: Path) -> None:
        result = install_hooks(platform="codex", project_dir=tmp_path, dry_run=True)
        assert result["ok"] is True
        assert not (tmp_path / ".codex").exists()
        assert any("WOULD install" in m for m in result["messages"])

    def test_all_platforms_listed(self) -> None:
        assert "cursor" in SUPPORTED_PLATFORMS
        assert "claude-code" in SUPPORTED_PLATFORMS
        assert "vscode" in SUPPORTED_PLATFORMS
        assert "generic" in SUPPORTED_PLATFORMS
        assert ADAPTER_PLATFORMS.issubset(SUPPORTED_PLATFORMS)
