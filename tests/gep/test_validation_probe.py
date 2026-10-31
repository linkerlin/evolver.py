"""Tests for validation_probe: layout-aware cascade adaptation.

Covers beginner-soft-default design (2026-10-31): discover project roots,
adapt/skip cascade commands, never create src/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evolver.gep import validation_probe


class TestDiscoverCheckRoots:
    """Test root directory discovery from project layout."""

    def test_empty_cwd_returns_empty(self, tmp_path: Path) -> None:
        """Empty project has no check roots."""
        roots = validation_probe.discover_check_roots(tmp_path)
        assert roots == []

    def test_src_and_tests_found(self, tmp_path: Path) -> None:
        """Standard Python layout with src/ and tests/."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        roots = validation_probe.discover_check_roots(tmp_path)
        assert "src" in roots
        assert "tests" in roots

    def test_lib_found_when_src_absent(self, tmp_path: Path) -> None:
        """Alternative lib/ directory."""
        (tmp_path / "lib").mkdir()
        roots = validation_probe.discover_check_roots(tmp_path)
        assert "lib" in roots

    def test_mixed_roots(self, tmp_path: Path) -> None:
        """Multiple conventional roots."""
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()
        (tmp_path / "tests").mkdir()
        roots = validation_probe.discover_check_roots(tmp_path)
        # Order doesn't matter for discovery, just presence
        assert set(roots) >= {"src", "lib", "tests"}

    def test_nested_not_discovered(self, tmp_path: Path) -> None:
        """Don't discover deeply nested directories."""
        (tmp_path / "vendor" / "pkg" / "src").mkdir(parents=True)
        roots = validation_probe.discover_check_roots(tmp_path)
        assert "src" not in roots  # Only top-level src/ matters

    def test_no_mkdir_side_effect(self, tmp_path: Path) -> None:
        """Discovery never creates directories."""
        validation_probe.discover_check_roots(tmp_path)
        assert not (tmp_path / "src").exists()
        assert not (tmp_path / "tests").exists()


class TestAdaptCascadeCommands:
    """Test cascade command adaptation based on layout."""

    def test_empty_cwd_skips_all_with_warnings(self, tmp_path: Path) -> None:
        """Empty project skips all stages."""
        commands = [
            {"command": ["ruff", "check", "src", "tests"]},
            {"command": ["mypy", "src"]},
            {"command": ["pytest", "-q"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert adapted == []
        assert len(warnings) >= 3
        assert any("ruff" in w for w in warnings)
        assert any("mypy" in w for w in warnings)
        assert any("pytest" in w for w in warnings)

    def test_src_and_tests_present_keeps_commands(self, tmp_path: Path) -> None:
        """Standard layout keeps cascade as-is."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        commands = [
            {"command": ["ruff", "check", "src", "tests"]},
            {"command": ["mypy", "src"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert len(adapted) == 2
        assert adapted[0]["command"] == ["ruff", "check", "src", "tests"]
        assert adapted[1]["command"] == ["mypy", "src"]
        assert warnings == []

    def test_lib_rewrites_src_arg(self, tmp_path: Path) -> None:
        """lib/ rewrite src arguments."""
        (tmp_path / "lib").mkdir()
        commands = [
            {"command": ["ruff", "check", "src"]},
            {"command": ["mypy", "src"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert len(adapted) == 2
        assert adapted[0]["command"] == ["ruff", "check", "lib"]
        assert adapted[1]["command"] == ["mypy", "lib"]
        assert len(warnings) == 0  # Rewrite is silent success

    def test_only_tests_dir_adapts_ruff_mypy(self, tmp_path: Path) -> None:
        """Only tests/ exists, adapt linters."""
        (tmp_path / "tests").mkdir()
        commands = [
            {"command": ["ruff", "check", "src", "tests"]},
            {"command": ["mypy", "src"]},
            {"command": ["pytest", "-q"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        # ruff can check tests/, mypy skipped (no src), pytest runs
        assert len(adapted) == 2
        assert adapted[0]["command"] == ["ruff", "check", "tests"]
        assert adapted[1]["command"] == ["pytest", "-q"]
        assert any("mypy" in w for w in warnings)

    def test_pytest_kept_even_without_tests_dir(self, tmp_path: Path) -> None:
        """pytest skipped if tests/ missing in empty project."""
        commands = [{"command": ["pytest", "-q"]}]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        # In empty project, pytest is skipped
        assert len(adapted) == 0
        # Warning explains why
        assert any("pytest" in w.lower() and "tests" in w.lower() for w in warnings)

    def test_preserves_timeout_and_other_fields(self, tmp_path: Path) -> None:
        """Adaptation preserves non-command fields."""
        (tmp_path / "lib").mkdir()
        commands = [{"command": ["mypy", "src"], "timeout_ms": 120_000}]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert len(adapted) == 1
        assert adapted[0]["command"] == ["mypy", "lib"]
        assert adapted[0]["timeout_ms"] == 120_000

    def test_non_python_commands_passed_through(self, tmp_path: Path) -> None:
        """Commands without src/tests args pass through unchanged."""
        commands = [
            {"command": ["npm", "test"]},
            {"command": ["make", "check"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert len(adapted) == 2
        assert adapted[0]["command"] == ["npm", "test"]
        assert adapted[1]["command"] == ["make", "check"]
        assert warnings == []

    def test_mixed_adaptable_and_passthrough(self, tmp_path: Path) -> None:
        """Mixed Python and non-Python commands."""
        (tmp_path / "lib").mkdir()
        commands = [
            {"command": ["ruff", "check", "src"]},
            {"command": ["npm", "run", "lint"]},
            {"command": ["mypy", "src"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert len(adapted) == 3
        assert adapted[0]["command"] == ["ruff", "check", "lib"]
        assert adapted[1]["command"] == ["npm", "run", "lint"]
        assert adapted[2]["command"] == ["mypy", "lib"]

    def test_empty_commands_list(self, tmp_path: Path) -> None:
        """Empty command list returns empty."""
        adapted, warnings = validation_probe.adapt_cascade_commands([], tmp_path)
        assert adapted == []
        assert warnings == []


class TestProbeIntegration:
    """Integration scenarios combining discovery and adaptation."""

    def test_toy_repo_no_layout_skips_python_checks(self, tmp_path: Path) -> None:
        """Toy repo with just a script.py skips all Python linters."""
        (tmp_path / "script.py").write_text("print('hello')")
        commands = [
            {"command": ["ruff", "check", "src", "tests"]},
            {"command": ["mypy", "src"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        assert adapted == []
        assert len(warnings) >= 2

    def test_partial_layout_adapts_subset(self, tmp_path: Path) -> None:
        """Partial layout adapts what it can."""
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "__init__.py").write_text("")
        commands = [
            {"command": ["ruff", "check", "src", "tests"]},
            {"command": ["mypy", "src"]},
            {"command": ["pytest"]},
        ]
        adapted, warnings = validation_probe.adapt_cascade_commands(commands, tmp_path)
        # ruff checks lib, mypy checks lib, pytest skipped (no tests/)
        assert len(adapted) == 2
        assert adapted[0]["command"] == ["ruff", "check", "lib"]
        assert adapted[1]["command"] == ["mypy", "lib"]
        assert any("pytest" in w for w in warnings)
