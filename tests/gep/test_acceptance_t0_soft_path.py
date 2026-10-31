"""Tests for T0 probe mode selection: soft-accept skips/minimizes checks."""
from __future__ import annotations

import pytest
from pathlib import Path

from evolver.gep.acceptance.t0_probe import determine_t0_mode, run_t0_with_mode


class TestT0Mode:
    def test_hard_accept_runs_full_t0(self) -> None:
        mode = determine_t0_mode(accept_type="hard", soft_accept=False)
        assert mode == "full"

    def test_soft_accept_runs_minimal_t0(self) -> None:
        mode = determine_t0_mode(accept_type="soft", soft_accept=True)
        assert mode == "minimal"

    def test_no_baseline_soft_skips_t0(self) -> None:
        mode = determine_t0_mode(accept_type="soft", soft_accept=True)
        assert mode in ("skip", "minimal")


class TestT0Execution:
    def test_skip_mode_returns_quickly(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="skip", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "skip"
        assert "duration_ms" in result
        assert result["duration_ms"] < 100

    def test_minimal_mode_runs_subset(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="minimal", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "minimal"
        assert "checks" in result
        assert len(result["checks"]) > 0

    def test_full_mode_runs_complete_suite(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="full", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "full"
        assert "checks" in result
