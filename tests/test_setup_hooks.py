"""Tests for evolver.adapters.setup_hooks."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.adapters.setup_hooks import (
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

    def test_cursor_hook(self, tmp_path: Path) -> None:
        result = install_hooks(platform="cursor", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "cursor"
        target = tmp_path / ".cursor" / "rules" / "evolver-gep.mdc"
        assert target.exists()
        content = target.read_text()
        assert "GEP Coding Rules" in content
        assert "Minimal changes" in content
        mcp = tmp_path / ".cursor" / "mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "evolver" in data.get("mcpServers", {})

    def test_claude_hook(self, tmp_path: Path) -> None:
        result = install_hooks(platform="claude-code", project_dir=tmp_path)
        assert result["ok"] is True
        assert result["platform"] == "claude-code"
        target = tmp_path / ".claude" / "AGENTS.md"
        assert target.exists()
        content = target.read_text()
        assert "Evolver Project Context" in content
        cmd = tmp_path / ".claude" / "commands" / "evolver-run.json"
        assert cmd.exists()
        data = json.loads(cmd.read_text())
        assert data["name"] == "evolver-run"

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

    def test_all_platforms_listed(self) -> None:
        assert "cursor" in SUPPORTED_PLATFORMS
        assert "claude-code" in SUPPORTED_PLATFORMS
        assert "vscode" in SUPPORTED_PLATFORMS
        assert "generic" in SUPPORTED_PLATFORMS
