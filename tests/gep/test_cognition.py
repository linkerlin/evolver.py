"""Tests for evolver.gep.cognition pipeline orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.cognition import (
    augment_signals,
    build_recall_section,
    flatten_recall_events,
    post_solidify_hooks,
)


class TestFlattenRecallEvents:
    def test_legacy_attempt(self) -> None:
        events = [
            {
                "type": "attempt",
                "event_id": "a1",
                "outcome": "success",
                "signals_snapshot": ["log_error"],
            }
        ]
        flat = flatten_recall_events(events)
        assert len(flat) == 1
        assert flat[0]["event_id"] == "a1"

    def test_memory_graph_outcome(self) -> None:
        events = [
            {
                "type": "MemoryGraphEvent",
                "kind": "outcome",
                "id": "out-1",
                "ts": "2026-01-01T00:00:00.000Z",
                "signal": {"signals": ["perf_bottleneck", "refactor"]},
                "gene": {"id": "gene-a", "category": "optimize"},
                "outcome": {"status": "success"},
            }
        ]
        flat = flatten_recall_events(events)
        assert len(flat) == 1
        assert flat[0]["signals_snapshot"] == ["perf_bottleneck", "refactor"]
        assert "gene-a" in flat[0]["mutation_summary"]


class TestBuildRecallSection:
    def test_injects_matching_memory_graph_outcome(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_RECALL_INJECT", "true")
        graph = tmp_path / "memory_graph.jsonl"
        graph.write_text(
            '{"type":"MemoryGraphEvent","kind":"outcome","id":"o1",'
            '"ts":"2026-06-01T00:00:00.000Z",'
            '"signal":{"signals":["refactor","cleanup"]},'
            '"gene":{"id":"g1","category":"optimize"},'
            '"outcome":{"status":"success"}}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(graph))

        section = build_recall_section(["refactor", "cleanup"])
        assert "Recall Hints" in section
        assert "g1" in section


class TestAugmentSignals:
    def test_explore_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOLVER_FF_ENABLE_EXPLORE", raising=False)
        base = ["log_error"]
        assert augment_signals(base) == base


class TestPostSolidifyHooks:
    def test_records_memory_outcome(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, temp_workspace: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_MEMORY_GRAPH", "true")
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "graph.jsonl"))
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))

        event = {
            "outcome": {"status": "success", "score": 1.0},
            "blast_radius": {"files": 1, "lines": 10},
        }
        last_run = {
            "run_id": "run-1",
            "signals": ["log_error"],
            "selected_gene_id": "gene-1",
        }
        result = post_solidify_hooks(event, last_run)
        assert result.get("memory_outcome") is True
        text = (tmp_path / "graph.jsonl").read_text(encoding="utf-8")
        assert "outcome" in text
