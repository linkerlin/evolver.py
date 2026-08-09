"""Tests for evolver.evolve.pipeline.diagnosis (Sprint B1 integration)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evolver.evolve.pipeline.diagnosis import (
    diagnosis_phase,
    load_persisted_analyses,
    run_diagnosis,
)


def _failed_event(eid: str, *, kind_hint: str = "timeout") -> dict:
    return {
        "id": eid,
        "outcome": {"status": "failed", "score": 0},
        "execution_trace": [
            {"tool": "python", "command_preview": "edit a.py",
             "error_signature": kind_hint},
            {"tool": "python", "command_preview": "edit b.py"},
        ],
    }


def _succeeded_event(eid: str) -> dict:
    return {"id": eid, "outcome": {"status": "success", "score": 1.0}}


@pytest.fixture
def _diagnosis_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_DIAGNOSIS", "1")


@pytest.fixture
def _tmp_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    assets = tmp_path / "gep"
    assets.mkdir()
    monkeypatch.setenv("GEP_ASSETS_DIR", str(assets))
    return assets


class TestFlagOffRegression:
    def test_flag_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_DIAGNOSIS", "0")
        ctx = {"recent_events": [_failed_event("e1")], "signals": ["log_error"]}
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        # Unchanged: no causal keys added.
        assert "causal_brief" not in result
        assert result["signals"] == ["log_error"]


class TestFlagOnDiagnosis:
    def test_no_failed_events_empty_brief(
        self,
        _diagnosis_on: None,
        _tmp_assets: Path,
    ) -> None:
        ctx = {
            "cycle_id": "c1",
            "recent_events": [_succeeded_event("e_ok")],
            "signals": [],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        assert result["causal_brief"] == ""
        assert result["signals"] == []

    def test_failed_event_produces_degraded_brief(
        self,
        _diagnosis_on: None,
        _tmp_assets: Path,
    ) -> None:
        ctx = {
            "cycle_id": "c1",
            "recent_events": [_failed_event("e_fail")],
            "signals": ["log_error"],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        assert "Causal Diagnosis" in result["causal_brief"]
        assert "e_fail" in result["causal_brief"]
        # degraded → unattributed root cause
        assert "unattributed" in result["causal_brief"]
        # no root_cause signal injected (degraded has none)
        assert "causal_signals_merged" not in result

    def test_persists_artifact_to_disk_c1(
        self,
        _diagnosis_on: None,
        _tmp_assets: Path,
    ) -> None:
        ctx = {
            "cycle_id": "cyc_abc",
            "recent_events": [_failed_event("e1"), _succeeded_event("e2")],
            "signals": [],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        ref = result["causal_analyses_ref"]
        artifact = Path(ref)
        assert artifact.exists()
        assert _tmp_assets.name in ref
        assert "diagnosis" in ref
        assert "cyc_abc" in ref
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["format"] == "evolver.diagnosis_artifact.v0"
        assert len(payload["analyses"]) == 1  # only the failed one
        assert payload["analyses"][0]["event_id"] == "e1"

    def test_load_persisted_analyses_round_trip(
        self,
        _diagnosis_on: None,
        _tmp_assets: Path,
    ) -> None:
        ctx = {
            "cycle_id": "cyc_rt",
            "recent_events": [_failed_event("e_rt")],
            "signals": [],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        ref = result["causal_analyses_ref"]
        loaded = load_persisted_analyses(ref)
        assert len(loaded) == 1
        assert loaded[0].event_id == "e_rt"

    def test_load_persisted_missing_file_returns_empty(self) -> None:
        assert load_persisted_analyses("/no/such/file.json") == []


class TestRunDiagnosis:
    def test_only_failed_events_analyzed(self) -> None:
        events = [_failed_event("f1"), _succeeded_event("s1"), _failed_event("f2")]
        analyses = run_diagnosis(events)
        assert {a.event_id for a in analyses} == {"f1", "f2"}

    def test_max_events_cap(self) -> None:
        events = [_failed_event(f"f{i}") for i in range(10)]
        analyses = run_diagnosis(events, max_events=3)
        assert len(analyses) == 3

    def test_non_dict_events_skipped(self) -> None:
        analyses = run_diagnosis(["nope", 42, _failed_event("ok")])  # type: ignore[list-item]
        assert len(analyses) == 1
        assert analyses[0].event_id == "ok"


class TestSignalInjectionC4:
    def test_no_signal_injection_when_degraded(
        self,
        _diagnosis_on: None,
        _tmp_assets: Path,
    ) -> None:
        # Degraded analysis (no LLM) → no root_cause → no signal injected.
        ctx = {
            "cycle_id": "c1",
            "recent_events": [_failed_event("e1")],
            "signals": ["existing"],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        assert result["signals"] == ["existing"]
        # (Signal injection of causal:root_cause:* is exercised via B2/L3 once
        # an LLM attributes root causes; here we assert the no-op path.)


class TestIntervalGating:
    def test_interval_skips_non_matching_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _tmp_assets: Path,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_DIAGNOSIS", "1")
        # DIAGNOSIS_INTERVAL is a module-level Final (import-time); patch the
        # name the phase reads directly, since env_int already bound at import.
        monkeypatch.setattr(
            "evolver.evolve.pipeline.diagnosis.DIAGNOSIS_INTERVAL", 5
        )
        ctx = {
            "cycle_num": 3,
            "cycle_id": "c3",
            "recent_events": [_failed_event("e1")],
            "signals": [],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        # interval 5, cycle 3 → 3 % 5 != 0 → skip → no causal_brief set
        assert "causal_brief" not in result

    def test_interval_runs_on_matching_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _tmp_assets: Path,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_DIAGNOSIS", "1")
        monkeypatch.setattr(
            "evolver.evolve.pipeline.diagnosis.DIAGNOSIS_INTERVAL", 5
        )
        ctx = {
            "cycle_num": 5,
            "cycle_id": "c5",
            "recent_events": [_failed_event("e1")],
            "signals": [],
        }
        result = asyncio.run(diagnosis_phase(dict(ctx)))
        assert "causal_brief" in result
