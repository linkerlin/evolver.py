"""Tests for cycle-side phase timing telemetry (round-42)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.evolve.runner import _record_cycle_phase_timings, _timed_phase


async def _fast(ctx: dict[str, Any]) -> dict[str, Any]:
    ctx["ran"] = True
    return ctx


async def _boom(ctx: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("phase failed")


class TestTimedPhase:
    async def test_records_monotonic_duration(self) -> None:
        ctx: dict[str, Any] = {}
        out = await _timed_phase(ctx, "collect", _fast)
        assert out["ran"] is True
        assert ctx["cycle_phase_timings"]["collect"] >= 0.0

    async def test_failed_phase_still_records(self) -> None:
        ctx: dict[str, Any] = {}
        with pytest.raises(RuntimeError):
            await _timed_phase(ctx, "hub", _boom)
        assert "hub" in ctx["cycle_phase_timings"], (
            "timing must be recorded on the failure path — the expensive "
            "phase is often the failing one"
        )


class TestRecordCyclePhaseTimings:
    def test_persists_into_swarm_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        evo = tmp_path / "evolution"
        evo.mkdir()
        state = evo / "swarm_state.json"
        state.write_text(json.dumps({"tick_count": 7}) + "\n", encoding="utf-8")
        monkeypatch.setenv("EVOLUTION_DIR", str(evo))

        _record_cycle_phase_timings({"cycle_phase_timings": {"collect": 0.1, "hub": 0.2}})

        data = json.loads(state.read_text(encoding="utf-8"))
        assert data["tick_count"] == 7, "existing fields must survive"
        assert data["last_tick_phase_timings"] == {"collect": 0.1, "hub": 0.2}
        assert data["last_tick_total_s"] == 0.3

    def test_no_timings_no_write(self, tmp_path: Path) -> None:
        # Missing/empty timings are a no-op, and a missing state file must
        # not be created by the recorder.
        _record_cycle_phase_timings({})
        _record_cycle_phase_timings({"cycle_phase_timings": {}})
        assert not (tmp_path / "swarm_state.json").exists()

    def test_corrupt_state_file_swallowed(self, tmp_path: Path) -> None:
        evo = tmp_path / "evolution"
        evo.mkdir()
        (evo / "swarm_state.json").write_text("not-json", encoding="utf-8")
        import os

        os.environ["EVOLUTION_DIR"] = str(evo)
        try:
            _record_cycle_phase_timings({"cycle_phase_timings": {"x": 1.0}})
        finally:
            del os.environ["EVOLUTION_DIR"]
        assert (evo / "swarm_state.json").read_text(encoding="utf-8") == "not-json"
