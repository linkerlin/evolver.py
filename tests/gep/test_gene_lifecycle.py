"""Tests for evolver.gep.gene_lifecycle (RSI P1-5, Library Drift)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import gene_lifecycle as gl


def _landing(gene_id: str, i: int, *, signals: tuple[str, ...] = ("log_error",)) -> dict[str, Any]:
    return {
        "id": f"evt_land_{gene_id}_{i}",
        "outcome": {"status": "success"},
        "mutation": {"landed_gene_ids": [gene_id]},
        "signals": list(signals),
    }


def _failure(i: int, *, signals: tuple[str, ...] = ("log_error",)) -> dict[str, Any]:
    return {"id": f"evt_fail_{i}", "outcome": {"status": "failed"}, "signals": list(signals)}


def _success(i: int, *, signals: tuple[str, ...] = ("hub_offline",)) -> dict[str, Any]:
    return {"id": f"evt_ok_{i}", "outcome": {"status": "success"}, "signals": list(signals)}


def _pad(n: int = 5, start: int = 100) -> list[dict[str, Any]]:
    return [_success(start + i) for i in range(n)]


def _zero_work_history(gene_id: str = "gene_dead") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(3):
        events.append(_landing(gene_id, i))
        events.append(_failure(i))
    events.extend(_pad())
    return events


class TestLandingStats:
    def test_counts_observations_and_resolutions(self) -> None:
        events = _zero_work_history()
        stats = gl.landing_stats(events)
        assert stats["gene_dead"] == {
            "landings": 3,
            "observations": 3,
            "resolved": 0,
            "recurred": 6,
            "last_index": 4,
        }

    def test_unknown_landings_excluded_from_observations(self) -> None:
        stats = gl.landing_stats([_landing("g_tail", 0)])
        assert stats["g_tail"]["landings"] == 1
        assert stats["g_tail"]["observations"] == 0
        assert stats["g_tail"]["resolved"] == 0

    def test_unrelated_failures_do_not_count_as_recurrence(self) -> None:
        events = [_landing("g_ok", 0), _failure(0, signals=("mypy_error",)), *_pad()]
        stats = gl.landing_stats(events)
        assert stats["g_ok"]["observations"] == 1
        assert stats["g_ok"]["resolved"] == 1
        assert stats["g_ok"]["recurred"] == 0

    def test_multi_gene_event_credits_every_landed_gene(self) -> None:
        event = {
            "id": "multi",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["g_a", "g_b"]},
            "signals": ["log_error"],
        }
        stats = gl.landing_stats([event, *_pad()])
        assert stats["g_a"]["landings"] == 1
        assert stats["g_b"]["landings"] == 1

    def test_script_only_gene_id_is_not_a_landing(self) -> None:
        event = {
            "id": "script_only",
            "outcome": {"status": "success"},
            "mutation": {"gene_id": "gene_script"},
            "signals": ["log_error"],
        }
        assert gl.landing_stats([event, *_pad()]) == {}


class TestEvaluator:
    def test_insufficient_evidence_no_transition(self) -> None:
        events: list[dict[str, Any]] = []
        for i in range(2):
            events.append(_landing("g_sparse", i))
            events.append(_failure(i))
        events.extend(_pad())
        assert gl.evaluate_gene_lifecycle(events, {}) == []

    def test_zero_work_reaches_under_review(self) -> None:
        transitions = gl.evaluate_gene_lifecycle(_zero_work_history(), {})
        assert len(transitions) == 1
        t = transitions[0]
        assert (t.gene_id, t.from_status, t.to_status, t.reason) == (
            "gene_dead",
            "active",
            "under_review",
            "zero_work_evidence",
        )
        assert t.evidence["observations_at_review"] == 3
        assert t.evidence["resolved_at_review"] == 0

    def test_retried_zero_work_retires(self) -> None:
        state = {
            "gene_dead": gl.GeneLifecycleRecord(
                gene_id="gene_dead",
                status="under_review",
                evidence={"observations_at_review": 3, "resolved_at_review": 0},
            )
        }
        events = [*_zero_work_history(), _landing("gene_dead", 9), _failure(9), *_pad(start=200)]
        transitions = gl.evaluate_gene_lifecycle(events, state)
        assert len(transitions) == 1
        assert transitions[0].to_status == "retired"
        assert transitions[0].reason == "zero_work_after_review"

    def test_resolution_revalidates(self) -> None:
        state = {
            "gene_dead": gl.GeneLifecycleRecord(
                gene_id="gene_dead",
                status="under_review",
                evidence={"observations_at_review": 3, "resolved_at_review": 0},
            )
        }
        events = [*_zero_work_history(), _landing("gene_dead", 9), *_pad(start=200)]
        transitions = gl.evaluate_gene_lifecycle(events, state)
        assert len(transitions) == 1
        assert transitions[0].to_status == "active"
        assert transitions[0].reason == "revalidated"

    def test_no_new_evidence_keeps_review(self) -> None:
        state = {
            "gene_dead": gl.GeneLifecycleRecord(
                gene_id="gene_dead",
                status="under_review",
                evidence={"observations_at_review": 3, "resolved_at_review": 0},
            )
        }
        assert gl.evaluate_gene_lifecycle(_zero_work_history(), state) == []

    def test_retired_is_terminal_for_the_engine(self) -> None:
        state = {
            "gene_dead": gl.GeneLifecycleRecord(
                gene_id="gene_dead",
                status="retired",
                evidence={"observations_at_review": 3, "resolved_at_review": 0},
            )
        }
        events = [*_zero_work_history(), _landing("gene_dead", 9), *_pad(start=200)]
        assert gl.evaluate_gene_lifecycle(events, state) == []


class TestPersistence:
    def test_evaluate_and_apply_writes_state_and_audit(self, temp_workspace: Path) -> None:
        events = _zero_work_history()
        result = gl.evaluate_and_apply(events, now="2026-09-18T00:00:00Z")
        assert result["ok"] is True
        assert len(result["transitions"]) == 1

        state = json.loads(gl.lifecycle_path().read_text(encoding="utf-8"))
        record = state["genes"]["gene_dead"]
        assert record["status"] == "under_review"
        assert record["reason"] == "zero_work_evidence"
        assert state["updated_at"] == "2026-09-18T00:00:00Z"

        audit = [
            json.loads(line)
            for line in gl.lifecycle_audit_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert audit[-1]["actor"] == "engine"
        assert audit[-1]["to_status"] == "under_review"

    def test_evaluate_and_apply_is_idempotent(self, temp_workspace: Path) -> None:
        events = _zero_work_history()
        first = gl.evaluate_and_apply(events)
        second = gl.evaluate_and_apply(events)
        assert first["ok"] is True
        assert second == {"ok": True, "transitions": []}

    def test_corrupt_store_refuses_evaluation(self, temp_workspace: Path) -> None:
        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        result = gl.evaluate_and_apply(_zero_work_history())
        assert result["ok"] is False
        assert result["error"] == "lifecycle_store_corrupt"
        assert path.read_text(encoding="utf-8") == "{not json"

    def test_load_lifecycle_strict_raises_on_corrupt(self, temp_workspace: Path) -> None:
        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(gl.GeneLifecycleStoreError):
            gl.load_lifecycle(strict=True)
        assert gl.load_lifecycle(strict=False) == {}

    def test_load_lifecycle_skips_malformed_records(self, temp_workspace: Path) -> None:
        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "genes": {
                        "g_bad": {"status": "bogus"},
                        "g_ok": {"gene_id": "g_ok", "status": "retired"},
                    },
                }
            ),
            encoding="utf-8",
        )
        records = gl.load_lifecycle()
        assert set(records) == {"g_ok"}
        assert records["g_ok"].status == "retired"

    def test_load_lifecycle_sets_fail_open_on_corrupt(self, temp_workspace: Path) -> None:
        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        assert gl.load_lifecycle_sets() == (set(), set())

    def test_load_lifecycle_sets_returns_both_statuses(self, temp_workspace: Path) -> None:
        gl.evaluate_and_apply(_zero_work_history())
        retired, review = gl.load_lifecycle_sets()
        assert review == {"gene_dead"}
        assert retired == set()

    def test_reinstate_returns_gene_to_active(self, temp_workspace: Path) -> None:
        gl.evaluate_and_apply(_zero_work_history())
        result = gl.reinstate_gene("gene_dead", note="human says try again")
        assert result["ok"] is True
        assert result["record"]["status"] == "active"
        assert result["record"]["reinstated_count"] == 1
        assert gl.status_map() == {"gene_dead": "active"}

        audit = [
            json.loads(line)
            for line in gl.lifecycle_audit_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert audit[-1]["actor"] == "human"
        assert audit[-1]["reason"] == "human_reinstate"

    def test_reinstate_rejects_active_or_unknown(self, temp_workspace: Path) -> None:
        assert gl.reinstate_gene("ghost") == {
            "ok": False,
            "error": "not_tracked",
            "gene_id": "ghost",
        }
        gl.evaluate_and_apply(_zero_work_history())
        assert gl.reinstate_gene("gene_dead")["ok"] is True
        again = gl.reinstate_gene("gene_dead")
        assert again["ok"] is False
        assert again["error"] == "already_active"

    def test_status_map_defaults_and_override(self, temp_workspace: Path) -> None:
        assert gl.status_map() == {}
        assert gl.status_map({"g": gl.GeneLifecycleRecord(gene_id="g")}) == {"g": "active"}
