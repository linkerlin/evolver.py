"""Tests for evolver.gep.validator.sandbox_executor."""

import pytest

from evolver.gep.validator.sandbox_executor import (
    _validate_command,
    _validate_script,
    execute_in_sandbox,
)


class TestValidateCommand:
    def test_valid_python(self):
        _validate_command(["python", "script.py"])

    def test_missing_script(self):
        with pytest.raises(ValueError, match="script path"):
            _validate_command(["python"])

    def test_forbidden_pip(self):
        with pytest.raises(ValueError):
            _validate_command(["pip", "install", "x"])

    def test_forbidden_eval(self):
        with pytest.raises(ValueError):
            _validate_command(["python", "-c", "print(1)"])

    def test_forbidden_shell(self):
        with pytest.raises(ValueError):
            _validate_command(["python", "script.py", ";", "rm", "-rf", "/"])


class TestValidateScript:
    def test_safe(self):
        _validate_script("def foo(): pass")

    def test_forbidden_os_system(self):
        with pytest.raises(ValueError):
            _validate_script("import os; os.system('ls')")

    def test_strict_blocks_socket_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_SANDBOX_STRICT", "1")
        with pytest.raises(ValueError, match="Network import blocked"):
            _validate_script("import socket\nprint('hi')")

    def test_forbidden_subprocess(self):
        with pytest.raises(ValueError):
            _validate_script("import subprocess; subprocess.call(['ls'])")

    def test_forbidden_exec(self):
        with pytest.raises(ValueError):
            _validate_script("exec('print(1)')")


class TestExecuteInSandbox:
    def test_hello_world(self):
        result = execute_in_sandbox("print('hello')", timeout_seconds=5)
        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert not result.timed_out

    def test_failure(self):
        result = execute_in_sandbox("raise ValueError('boom')", timeout_seconds=5)
        assert result.exit_code != 0
        assert "boom" in result.stderr

    def test_timeout(self):
        result = execute_in_sandbox("import time; time.sleep(100)", timeout_seconds=1)
        assert result.timed_out
        assert result.exit_code == -1

    def test_temp_cleanup(self):
        import os
        import tempfile

        before = set(os.listdir(tempfile.gettempdir()))
        execute_in_sandbox("print('ok')", timeout_seconds=5)
        after = set(os.listdir(tempfile.gettempdir()))
        # Should not leave evolver-sandbox dirs
        new_dirs = after - before
        assert not any("evolver-sandbox" in d for d in new_dirs)

    def test_dangerous_script_rejected(self):
        result = execute_in_sandbox("import os; os.system('ls')", timeout_seconds=5)
        assert result.exit_code == -1
        assert "Dangerous" in result.stderr

    def test_timing(self):
        result = execute_in_sandbox("print('ok')", timeout_seconds=5)
        assert result.elapsed_ms >= 0


class TestRequireIsolation:
    """Sprint 24.3: fail-closed refusal when isolation is unavailable."""

    def test_refuses_without_isolation(self, monkeypatch):
        from evolver.gep.validator import sandbox_executor as se

        monkeypatch.setenv("EVOLVER_SANDBOX_REQUIRE_ISOLATION", "1")
        monkeypatch.setattr(se, "network_isolation_available", lambda: False)

        def _explode(*args, **kwargs):  # must never be reached
            raise AssertionError("subprocess ran despite refused isolation")

        monkeypatch.setattr(se.subprocess, "run", _explode)
        result = se.execute_in_sandbox("print('hello')", timeout_seconds=5)
        assert result.refused
        assert result.exit_code == -1
        assert "sandbox_isolation_unavailable" in result.stderr

    def test_runs_when_required_and_available(self, monkeypatch):
        from evolver.gep.validator import sandbox_executor as se

        monkeypatch.setenv("EVOLVER_SANDBOX_REQUIRE_ISOLATION", "1")
        monkeypatch.setattr(se, "network_isolation_available", lambda: True)
        result = se.execute_in_sandbox("print('isolated-ok')", timeout_seconds=5)
        assert not result.refused
        assert result.exit_code == 0
        assert "isolated-ok" in result.stdout

    def test_flag_off_keeps_best_effort(self, monkeypatch):
        from evolver.gep.validator import sandbox_executor as se

        monkeypatch.delenv("EVOLVER_SANDBOX_REQUIRE_ISOLATION", raising=False)
        monkeypatch.setattr(se, "network_isolation_available", lambda: False)
        result = se.execute_in_sandbox("print('best-effort')", timeout_seconds=5)
        assert not result.refused
        assert "best-effort" in result.stdout

    def test_probe_caches_per_process(self, monkeypatch):
        from evolver.gep.validator import sandbox_executor as se

        monkeypatch.setattr(se.platform, "system", lambda: "Linux")
        monkeypatch.setattr(se, "_isolation_available", None)
        calls = []
        monkeypatch.setattr(
            se.subprocess,
            "run",
            lambda *a, **kw: calls.append(1) or type("R", (), {"returncode": 0})(),
        )
        assert se.network_isolation_available()
        assert se.network_isolation_available()
        assert len(calls) == 1
