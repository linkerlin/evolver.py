"""Tests for evolver.adapters.opencode."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.adapters import opencode


class TestBuildPluginSource:
    def test_contains_header(self) -> None:
        source = opencode.build_plugin_source(Path("/hooks"))
        assert opencode.PLUGIN_HEADER in source

    def test_contains_module_exports(self) -> None:
        source = opencode.build_plugin_source(Path("/hooks"))
        assert "module.exports" in source
        assert "Evolver" in source

    def test_contains_python_executable(self) -> None:
        source = opencode.build_plugin_source(Path("/hooks"))
        assert "python" in source.lower()


class TestIsEvolverManagedPluginFile:
    def test_true(self, tmp_path: Path) -> None:
        p = tmp_path / "evolver.js"
        p.write_text(opencode.PLUGIN_HEADER + "\n// more", encoding="utf-8")
        assert opencode._is_evolver_managed_plugin_file(p) is True

    def test_false_no_marker(self, tmp_path: Path) -> None:
        p = tmp_path / "evolver.js"
        p.write_text("// custom plugin", encoding="utf-8")
        assert opencode._is_evolver_managed_plugin_file(p) is False

    def test_false_missing(self, tmp_path: Path) -> None:
        assert opencode._is_evolver_managed_plugin_file(tmp_path / "evolver.js") is False


class TestInstall:
    def test_writes_plugin(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        result = opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["ok"] is True
        plugin = config_root / ".opencode" / "plugins" / "evolver.js"
        assert plugin.exists()

    def test_skips_when_installed(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        assert result["skipped"] is True
        assert result.get("plugin_path") is not None

    def test_force_overwrites(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = opencode.install(config_root=config_root, evolver_root=evolver_root, force=True)
        assert result.get("skipped") is not True

    def test_injects_agents_md(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        agents_md = config_root / "AGENTS.md"
        assert agents_md.exists()
        assert "evolver-evolution-memory" in agents_md.read_text(encoding="utf-8")


class TestVerify:
    def test_all_pass(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        report = opencode.verify(config_root=config_root)
        assert report["ok"] is True
        checks = {c["id"]: c for c in report["checks"]}
        assert checks["plugin_file_present"]["ok"] is True
        assert checks["plugin_managed_marker"]["ok"] is True
        assert checks["plugin_loadable"]["ok"] is True

    def test_missing_plugin(self, tmp_path: Path) -> None:
        report = opencode.verify(config_root=tmp_path / "project")
        assert report["ok"] is False
        checks = {c["id"]: c for c in report["checks"]}
        assert checks["plugin_file_present"]["ok"] is False


class TestPrintVerifyReport:
    def test_outputs(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = {
            "plugin_path": "/p",
            "hooks_dir": "/h",
            "config_root": "/c",
            "checks": [
                {"id": "a", "ok": True, "detail": "ok"},
                {"id": "b", "ok": False, "detail": "fail"},
            ],
            "note": "note",
        }
        opencode.print_verify_report(report)
        captured = capsys.readouterr()
        assert "Verify report" in captured.out
        assert "[OK]" in captured.out
        assert "[FAIL]" in captured.out


class TestUninstall:
    def test_removes_plugin(self, tmp_path: Path) -> None:
        config_root = tmp_path / "project"
        evolver_root = tmp_path / "evolver"
        opencode.install(config_root=config_root, evolver_root=evolver_root, force=False)
        result = opencode.uninstall(config_root=config_root, evolver_root=evolver_root)
        assert result["removed"] is True
        plugin = config_root / ".opencode" / "plugins" / "evolver.js"
        assert not plugin.exists()

    def test_no_plugin_found(self, tmp_path: Path) -> None:
        result = opencode.uninstall(config_root=tmp_path / "project", evolver_root=tmp_path)
        assert result["removed"] is False
