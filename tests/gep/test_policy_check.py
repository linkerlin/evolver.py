"""Tests for evolver.gep.policy_check."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evolver.gep.policy_check import PolicyReport, PolicyViolation, check_policy


class TestBlastRadius:
    def test_files_under_cap(self):
        files = ["a.py", "b.py"]
        report = check_policy(changed_files=files, untracked_files=[], max_files=10, max_lines=1000)
        assert report.ok
        assert not any(v.rule == "blast_radius_files" for v in report.violations)

    def test_files_over_cap(self):
        files = [f"f{i}.py" for i in range(30)]
        report = check_policy(changed_files=files, untracked_files=[], max_files=20, max_lines=1000)
        assert not report.ok
        assert any(v.rule == "blast_radius_files" and v.severity == "critical" for v in report.violations)

    def test_lines_over_cap(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_text("\n".join(f"x = {i}" for i in range(500)), encoding="utf-8")
        with patch("evolver.gep.policy_check.get_workspace_root", return_value=tmp_path):
            report = check_policy(changed_files=["big.py"], untracked_files=[], max_files=10, max_lines=100)
        assert not report.ok
        assert any(v.rule == "blast_radius_lines" for v in report.violations)


class TestProtectedPaths:
    def test_critical_file_blocked(self):
        report = check_policy(changed_files=[".env"], untracked_files=[])
        assert not report.ok
        assert any(".env" in v.message for v in report.violations)

    def test_self_protection_blocked(self):
        report = check_policy(changed_files=["evolver/core.py"], untracked_files=[])
        assert not report.ok
        assert any("self_protection" == v.rule for v in report.violations)

    def test_secret_file_blocked(self):
        report = check_policy(changed_files=["config/secrets.json"], untracked_files=[])
        assert not report.ok
        assert any("secret_file" == v.rule for v in report.violations)


class TestSecretLeaks:
    def test_no_leak(self):
        report = check_policy(diff_text="some normal code", changed_files=[], untracked_files=[])
        assert report.ok

    def test_bearer_leak(self):
        diff = 'Authorization: Bearer sk-1234567890abcdefghij'
        report = check_policy(diff_text=diff, changed_files=[], untracked_files=[])
        assert not report.ok
        assert any(v.rule == "secret_leak" for v in report.violations)


class TestRollbackSafety:
    def test_hard_reset_warning(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_ROLLBACK_MODE", "hard")
        report = check_policy(changed_files=[], untracked_files=["new_file.py"])
        assert any(v.rule == "rollback_hard_untracked" for v in report.violations)

    def test_none_mode_warning(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_ROLLBACK_MODE", "none")
        report = check_policy(changed_files=[], untracked_files=[])
        assert any(v.rule == "rollback_mode_none" for v in report.violations)

    def test_stash_with_protected_warning(self):
        report = check_policy(changed_files=["pyproject.toml"], untracked_files=[])
        assert any(v.rule == "rollback_protected_change" for v in report.violations)


class TestReport:
    def test_has_critical_property(self):
        report = PolicyReport(ok=False, violations=[
            PolicyViolation("x", "critical", "msg"),
            PolicyViolation("y", "warning", "msg2"),
        ])
        assert report.has_critical

    def test_no_critical(self):
        report = PolicyReport(ok=True, violations=[
            PolicyViolation("y", "warning", "msg2"),
        ])
        assert not report.has_critical
