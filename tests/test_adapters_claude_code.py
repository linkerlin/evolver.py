"""Tests for evolver.adapters.claude_code."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.adapters import claude_code


class TestBuildHooks:
    def test_structure(self, tmp_path: Path) -> None:
        hooks = claude_code.build_hooks(tmp_path)
        assert "hooks" in hooks
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            assert event in hooks["hooks"]
            entries = hooks["hooks"][event]
            assert isinstance(entries, list)
            assert len(entries) > 0

    def test_commands_use_python(self, tmp_path: Path) -> None:
        hooks = claude_code.build_hooks(tmp_path)
        for event in hooks["hooks"].values():
            for entry in event:
                for h in entry.get("hooks", []):
                    assert "python" in h["command"] or "python" in h["command"].lower()


class TestInstall:
    def test_creates_settings_json(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        result = claude_code.install(
            config_root=config_root, evolver_root=evolver_root, force=False
        )
        assert result["ok"] is True
        assert (config_root / ".claude" / "settings.json").exists()

    def test_skips_when_already_installed(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        claude_code.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = claude_code.install(
            config_root=config_root, evolver_root=evolver_root, force=False
        )
        assert result["skipped"] is True

    def test_force_overwrites(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        claude_code.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = claude_code.install(config_root=config_root, evolver_root=evolver_root, force=True)
        assert result.get("skipped") is not True
        assert result["ok"] is True

    def test_injects_claude_md(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        claude_code.install(config_root=config_root, evolver_root=evolver_root, force=False)
        claude_md = config_root / "CLAUDE.md"
        assert claude_md.exists()
        assert "evolver-evolution-memory" in claude_md.read_text(encoding="utf-8")


class TestUninstall:
    def test_removes_hooks(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        claude_code.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = claude_code.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["ok"] is True
        assert result["removed"] is True

    def test_no_hooks_found(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        result = claude_code.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["removed"] is False

    def test_cleans_nested_hooks(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        claude_dir = config_root / ".claude"
        claude_dir.mkdir(parents=True)
        settings = claude_dir / "settings.json"
        data = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "evolver-session-start.py",
                                "timeout": 3,
                            },
                            {
                                "type": "command",
                                "command": "user-custom.py",
                                "timeout": 3,
                            },
                        ],
                    }
                ]
            },
            "_evolver_managed": True,
        }
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = claude_code.uninstall(config_root=config_root, evolver_root=tmp_path)
        assert result["removed"] is True
        cleaned = json.loads(settings.read_text(encoding="utf-8"))
        # _evolver_managed removed
        assert "_evolver_managed" not in cleaned
        # evolver command removed, user command kept
        session = cleaned.get("hooks", {}).get("SessionStart", [])
        assert len(session) == 1
        assert len(session[0]["hooks"]) == 1
        assert session[0]["hooks"][0]["command"] == "user-custom.py"
