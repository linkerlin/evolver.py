"""Tests for evolver.gep.acceptance.t0_frozen (Sprint A1)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from evolver.gep.acceptance.t0_frozen import (
    discover_test_ids,
    freeze_snapshot,
    load_snapshot,
    parse_pytest_summary,
    run_pass_rate,
    snapshot_hash,
)


class TestSnapshotHash:
    def test_order_independent(self) -> None:
        assert snapshot_hash(["a::t1", "a::t2"]) == snapshot_hash(["a::t2", "a::t1"])

    def test_different_sets_differ(self) -> None:
        assert snapshot_hash(["a::t1"]) != snapshot_hash(["a::t2"])

    def test_hex_prefix_length(self) -> None:
        h = snapshot_hash(["x"])
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestFreezeLoadRoundTrip:
    def test_freeze_then_load(self, tmp_path: Path) -> None:
        ids = ["mod::test_a", "mod::test_b"]
        path = freeze_snapshot(ids, tmp_path / "snap")
        assert path.exists()
        assert path.name.startswith("t0_")
        loaded = load_snapshot(path)
        assert loaded == sorted(ids)

    def test_freeze_idempotent(self, tmp_path: Path) -> None:
        ids = ["a::t1"]
        p1 = freeze_snapshot(ids, tmp_path / "s")
        p2 = freeze_snapshot(ids, tmp_path / "s")
        assert p1 == p2  # same hash → same path, not rewritten

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        assert load_snapshot(tmp_path / "nope.txt") == []


class TestParsePytestSummary:
    @pytest.mark.parametrize(
        ("stdout", "total", "expected"),
        [
            ("3 passed in 0.10s", 3, (3, 3)),
            ("2 passed, 1 failed in 0.10s", 3, (2, 3)),
            ("1 passed, 2 failed, 1 error in 0.10s", 4, (1, 4)),
            ("0 passed in 0.10s", 3, (0, 3)),
            ("no tests ran", 3, (0, 3)),  # unparseable → 0 passed (fail-safe)
            ("", 0, (0, 0)),
        ],
    )
    def test_cases(self, stdout: str, total: int, expected: tuple[int, int]) -> None:
        assert parse_pytest_summary(stdout, total) == expected


def _make_tiny_project(root: Path) -> None:
    """Create a tiny pytest project: 2 passing tests + 1 failing test."""
    (root / "test_ok.py").write_text(
        textwrap.dedent(
            """
            def test_one():
                assert 1 + 1 == 2

            def test_two():
                assert "a" in "abc"
            """
        ),
        encoding="utf-8",
    )
    (root / "test_bad.py").write_text(
        textwrap.dedent(
            """
            def test_fails():
                assert 1 == 2
            """
        ),
        encoding="utf-8",
    )


@pytest.mark.timeout(60)
class TestSubprocessIntegration:
    """Real pytest subprocess (slower; verifies the actual eval path)."""

    def test_discover_and_run_pass_rate(self, tmp_path: Path) -> None:
        _make_tiny_project(tmp_path)
        ids = discover_test_ids(tmp_path)
        # 3 tests collected (2 ok + 1 bad)
        assert len(ids) == 3
        passed, total = run_pass_rate(ids, tmp_path)
        assert total == 3
        assert passed == 2  # 2 pass, 1 fails

    def test_freeze_then_run_uses_frozen_set(self, tmp_path: Path) -> None:
        _make_tiny_project(tmp_path)
        ids = discover_test_ids(tmp_path)
        snap = freeze_snapshot(ids, tmp_path / "snap")
        frozen = load_snapshot(snap)
        passed, total = run_pass_rate(frozen, tmp_path)
        assert total == 3
        assert passed == 2

    def test_empty_ids_returns_zero(self, tmp_path: Path) -> None:
        passed, total = run_pass_rate([], tmp_path)
        assert (passed, total) == (0, 0)
