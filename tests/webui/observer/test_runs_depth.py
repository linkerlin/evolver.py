"""Depth tests for multi-source runs list / detail."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.runs import get_run, list_runs, runs_history


def test_list_runs_from_events(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evo"))  # type: ignore[attr-defined]
    (tmp_path / "evo").mkdir()
    events = [
        {"type": "cycle_end", "run_id": "r1", "outcome": "success", "timestamp": 1.0},
        {"type": "cycle_end", "run_id": "r2", "outcome": "failure", "timestamp": 2.0},
        {"type": "noise", "run_id": "r3"},
    ]
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    result = list_runs(limit=10, memory_dir=tmp_path)
    assert result["total"] == 2
    statuses = {it["runId"]: it["status"] for it in result["items"]}
    assert statuses["r1"] == "success"
    assert statuses["r2"] == "failed"


def test_list_runs_merges_call_log(tmp_path: Path, monkeypatch: object) -> None:
    evo = tmp_path / "evo"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))  # type: ignore[attr-defined]
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    (evo / "asset_call_log.jsonl").write_text(
        json.dumps(
            {
                "run_id": "r_only_calls",
                "action": "asset_reuse",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = list_runs(limit=10, memory_dir=tmp_path)
    ids = {it["runId"] for it in result["items"]}
    assert "r_only_calls" in ids


def test_get_run_includes_evidence(tmp_path: Path, monkeypatch: object) -> None:
    evo = tmp_path / "evo"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))  # type: ignore[attr-defined]
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "home"))  # type: ignore[attr-defined]
    (tmp_path / "home").mkdir()
    events = [
        {
            "type": "EvolutionEvent",
            "run_id": "r9",
            "gene_id": "g1",
            "outcome": {"status": "success"},
            "timestamp": 10.0,
            "summary": "ok",
        }
    ]
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    (evo / "asset_call_log.jsonl").write_text(
        json.dumps({"run_id": "r9", "action": "asset_reuse", "tokens_saved": 12}) + "\n",
        encoding="utf-8",
    )
    detail = get_run("r9", memory_dir=tmp_path)
    assert detail is not None
    assert detail["event_count"] == 1
    assert detail["asset_call_count"] == 1
    assert detail["status"] in ("success", "unknown", "running")


def test_runs_history_still_works(tmp_path: Path) -> None:
    events = [
        {"type": "cycle_end", "outcome": "success", "timestamp": 1.0, "run_id": "a"},
        {"type": "cycle_end", "outcome": "failure", "timestamp": 2.0, "run_id": "b"},
    ]
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    result = runs_history(memory_dir=tmp_path)
    assert result["total_cycles"] == 2
    assert result["successes"] == 1
