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
