"""Tests for evolver.gep.exec_bridge.

Equivalent to test/execBridgeSpawnNpmShim.test.js — covers the npm .cmd shim
resolver on Windows and its POSIX no-op behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from evolver.gep import exec_bridge


def _real_npm_shim(rel_entry: str) -> str:
    """Generate a real npm-cli Windows .cmd shim (verbatim format)."""
    return "\r\n".join(
        [
            "@ECHO off",
            "GOTO start",
            ":find_dp0",
            "SET dp0=%~dp0",
            "EXIT /b",
            ":start",
            "SETLOCAL",
            "CALL :find_dp0",
            "",
            'IF EXIST "%dp0%\\node.exe" (',
            '  SET "_prog=%dp0%\\node.exe"',
            ") ELSE (",
            '  SET "_prog=node"',
            "  SET PATHEXT=%PATHEXT:;.JS;=;%;",
            ")",
            "",
            'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\'
            + rel_entry
            + '" %*',
            "",
        ]
    )


class TestPlatformGating:
    def test_returns_none_on_posix(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "linux"):
            shim = tmp_path / "claude.cmd"
            shim.write_text(_real_npm_shim("cli.js"), encoding="utf-8")
            assert exec_bridge.resolve_npm_cmd_shim(str(shim), []) is None

    def test_returns_none_for_non_cmd(self) -> None:
        with patch.object(sys, "platform", "win32"):
            assert exec_bridge.resolve_npm_cmd_shim("node.exe", []) is None
            assert exec_bridge.resolve_npm_cmd_shim("claude", []) is None

    def test_returns_none_for_empty(self) -> None:
        with patch.object(sys, "platform", "win32"):
            assert exec_bridge.resolve_npm_cmd_shim(None, []) is None
            assert exec_bridge.resolve_npm_cmd_shim("", []) is None


class TestShimParsing:
    def test_rewrites_real_shim(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            rel = str(Path("node_modules") / "@anthropic-ai" / "claude-code" / "cli.js")
            shim = tmp_path / "claude.cmd"
            shim.write_text(_real_npm_shim(rel), encoding="utf-8")
            entry = tmp_path / rel
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text("", encoding="utf-8")

            out = exec_bridge.resolve_npm_cmd_shim(str(shim), ["-p", "hello"])
            assert out is not None
            bin_path, args = out
            assert bin_path == sys.executable
            assert args[0] == str(entry.resolve())
            assert args[1:] == ["-p", "hello"]

    def test_handles_missing_js_extension(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            rel = str(Path("node_modules") / "@anthropic-ai" / "sdk" / "bin" / "cli")
            shim = tmp_path / "sdk.cmd"
            shim.write_text(_real_npm_shim(rel), encoding="utf-8")
            entry = tmp_path / (rel + ".js")
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text("", encoding="utf-8")

            out = exec_bridge.resolve_npm_cmd_shim(str(shim), [])
            assert out is not None

    def test_returns_none_for_custom_wrapper(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            shim = tmp_path / "custom.cmd"
            shim.write_text(
                '@echo off\r\nrem custom one-off wrapper\r\nnode "C:\\my\\script.js" %*\r\n',
                encoding="utf-8",
            )
            assert exec_bridge.resolve_npm_cmd_shim(str(shim), []) is None

    def test_returns_none_for_missing_entry(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            rel = str(Path("node_modules") / "missing-pkg" / "cli.js")
            shim = tmp_path / "orphan.cmd"
            shim.write_text(_real_npm_shim(rel), encoding="utf-8")
            # intentionally do NOT create the entry file
            assert exec_bridge.resolve_npm_cmd_shim(str(shim), []) is None

    def test_returns_none_for_unreadable_shim(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            missing = tmp_path / "does-not-exist.cmd"
            assert exec_bridge.resolve_npm_cmd_shim(str(missing), []) is None

    def test_preserves_scope_segment(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            rel = str(Path("node_modules") / "@openai" / "codex" / "dist" / "cli.js")
            shim = tmp_path / "codex.cmd"
            shim.write_text(_real_npm_shim(rel), encoding="utf-8")
            entry = tmp_path / rel
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text("", encoding="utf-8")

            out = exec_bridge.resolve_npm_cmd_shim(str(shim), [])
            assert out is not None
            assert "@openai" in out[1][0]


class TestSafeSpawnArgs:
    def test_passthrough_when_no_shim(self) -> None:
        with patch.object(sys, "platform", "linux"):
            bin_path, args = exec_bridge.safe_spawn_args("evolver", ["--loop"])
            assert bin_path == "evolver"
            assert args == ["--loop"]

    def test_resolves_when_shim(self, tmp_path: Path) -> None:
        with patch.object(sys, "platform", "win32"):
            rel = str(Path("node_modules") / "@evomap" / "evolver" / "index.js")
            shim = tmp_path / "evolver.cmd"
            shim.write_text(_real_npm_shim(rel), encoding="utf-8")
            entry = tmp_path / rel
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text("", encoding="utf-8")

            bin_path, _args = exec_bridge.safe_spawn_args(str(shim), [])
            assert bin_path == sys.executable
