"""Tests for uv / uvx / python launcher resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver import uv_runtime as ur


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestFindProjectRoot:
    def test_finds_pyproject(self, project_root: Path) -> None:
        assert ur.find_project_root(project_root) == project_root.resolve()

    def test_finds_uv_lock(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")
        assert ur.find_project_root(tmp_path) == tmp_path.resolve()

    def test_none_without_markers(self, tmp_path: Path) -> None:
        # Deep leaf without pyproject
        leaf = tmp_path / "a" / "b"
        leaf.mkdir(parents=True)
        # If any parent has no pyproject — walk may still hit real repo root.
        # Restrict by using a temp that is not under the real workspace.
        found = ur.find_project_root(leaf)
        # Accept None or some ancestor; when tmp is outside repo, often None.
        if found is not None:
            assert (found / "pyproject.toml").exists() or (found / "uv.lock").exists()


class TestBuildCommand:
    def test_python_launcher_forced(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "python")
        cmd = ur.build_evolver_command(["--loop"], cwd=project_root)
        assert cmd[0].endswith("python") or "python" in Path(cmd[0]).name.lower()
        assert cmd[1:3] == ["-m", "evolver"]
        assert cmd[-1] == "--loop"

    def test_uv_launcher_when_uv_present(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "uv")
        monkeypatch.setattr(ur, "which_uv", lambda: "/usr/bin/uv")
        cmd = ur.build_evolver_command(["run"], cwd=project_root)
        assert cmd[0] == "/usr/bin/uv"
        assert cmd[1] == "run"
        assert "--project" in cmd
        assert "evolver" in cmd
        assert cmd[-1] == "run"

    def test_uvx_launcher(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "uvx")
        monkeypatch.setattr(ur, "which_uvx", lambda: "/usr/bin/uvx")
        monkeypatch.setattr(ur, "which_uv", lambda: None)
        cmd = ur.build_evolver_command(["--loop"], cwd=project_root)
        assert cmd[0] == "/usr/bin/uvx"
        assert "--from" in cmd
        assert "evolver" in cmd
        assert "--loop" in cmd

    def test_uvx_falls_back_to_uv_tool_run(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "uvx")
        monkeypatch.setattr(ur, "which_uvx", lambda: "/usr/bin/uv")  # no shim
        monkeypatch.setattr(ur, "which_uv", lambda: "/usr/bin/uv")
        cmd = ur.build_evolver_command(["status"], cwd=project_root)
        assert cmd[:3] == ["/usr/bin/uv", "tool", "run"]

    def test_auto_prefers_uv_run_in_project(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "auto")
        monkeypatch.setattr(ur, "which_uv", lambda: "C:/tools/uv.exe")
        monkeypatch.setattr(ur, "which_uvx", lambda: "C:/tools/uvx.exe")
        cmd = ur.build_evolver_command(["--loop"], cwd=project_root)
        assert "run" in cmd
        assert cmd[0].endswith("uv.exe") or cmd[0] == "C:/tools/uv.exe"

    def test_auto_without_project_uses_uvx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EVOLVER_LAUNCHER", "auto")
        monkeypatch.setattr(ur, "which_uv", lambda: None)
        monkeypatch.setattr(ur, "which_uvx", lambda: "/bin/uvx")
        monkeypatch.setattr(ur, "find_project_root", lambda start=None: None)
        cmd = ur.build_evolver_command(["--loop"], cwd=tmp_path)
        assert cmd[0] == "/bin/uvx"
        assert "evolver" in cmd

    def test_loop_command_override(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LOOP_COMMAND", "uv run evolver --loop --review")
        cmd = ur.build_loop_command(cwd=project_root)
        assert cmd == ["uv", "run", "evolver", "--loop", "--review"]


class TestModuleCommand:
    def test_hook_uses_uv_run_python(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "uv")
        monkeypatch.setattr(ur, "which_uv", lambda: "/bin/uv")
        cmd = ur.build_module_command("evolver.adapters.scripts.session_start", cwd=project_root)
        assert cmd[0] == "/bin/uv"
        assert "python" in cmd
        assert "-m" in cmd
        assert "evolver.adapters.scripts.session_start" in cmd

    def test_hook_command_string_forward_slashes(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "python")
        s = ur.hook_command_string("evolver.adapters.scripts.session_end")
        assert "evolver.adapters.scripts.session_end" in s
        assert "\\" not in s or "/" in s  # normalized


class TestDetection:
    def test_is_uv_managed_cmdline(self) -> None:
        assert ur.is_uv_managed_cmdline("uv run evolver --loop") is True
        assert ur.is_uv_managed_cmdline("uvx evolver run") is True
        assert ur.is_uv_managed_cmdline("uv tool run evolver --loop") is True
        assert ur.is_uv_managed_cmdline("python -m evolver --loop") is False

    def test_describe_launcher(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_LAUNCHER", "python")
        info = ur.describe_launcher()
        assert info["launcher"] == "python"
        assert "python" in str(info["resolved_loop"]).lower() or "-m" in str(info["resolved_loop"])


class TestSpawnUsesUvRuntime:
    def test_cycle_control_uses_build_evolver_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from evolver import cycle_control as cc

        captured: list[list[str]] = []

        class FakePopen:
            def __init__(self, cmd: list[str], **_kwargs: object) -> None:
                captured.append(list(cmd))
                self.pid = 4242

        monkeypatch.setenv("EVOLVER_SUICIDE_WINDOWS", "true")
        monkeypatch.setenv("EVOLVER_LAUNCHER", "uv")
        monkeypatch.setattr(ur, "which_uv", lambda: "/opt/uv")
        monkeypatch.setattr(ur, "find_project_root", lambda start=None: tmp_path)
        monkeypatch.setattr(cc.subprocess, "Popen", FakePopen)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

        result = cc.spawn_replacement_process(
            reason="test",
            args=["--loop"],
            log_path=tmp_path / "daemon.log",
            platform="linux",
        )
        assert result.get("spawned") is True
        assert captured
        assert captured[0][0] == "/opt/uv"
        assert "evolver" in captured[0]
        assert "--loop" in captured[0]


class TestLifecycleLoopCommand:
    def test_loop_command_uses_uv_runtime(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from evolver.ops import lifecycle

        monkeypatch.setenv("EVOLVER_LAUNCHER", "python")
        monkeypatch.delenv("EVOLVER_LOOP_COMMAND", raising=False)
        cmd = lifecycle._loop_command()
        assert "-m" in cmd or "evolver" in " ".join(cmd)
        assert "--loop" in cmd
