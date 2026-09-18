"""RSI P1-4: dispatch assembles the failure-side evidence pack into the prompt.

The executor must see what THIS signal family already tried (outcomes,
rejection reasons, duplicate fingerprints) before the Selected Gene advice —
selection becomes retrieval augmentation, not the sole decision path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evolver.evolve.pipeline.dispatch import dispatch_phase


@pytest.fixture
def _ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    gep = tmp_path / "gep"
    gep.mkdir()
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(ws))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return ws


def _ctx(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "cycle_id": "c1",
        "run_id": "r1",
        "signals": ["log_error"],
        "selected_gene": {"id": "g1"},
        "mutation": {"id": "m1", "validation": []},
        "scan_time_iso": "2026-01-01T00:00:00Z",
        "genes": [],
        "hub_hit": {},
        "hub_lessons": [],
        "recent_events": [],
    }
    base.update(overrides)
    return base


def _family_fail_event() -> dict[str, Any]:
    return {
        "id": "evt_fail_prior",
        "gene_id": "g1",
        "outcome": {"status": "failed", "error": "validation_failed"},
        "mutation": {"category": "repair"},
        "signals": ["log_error"],
        "novelty_added": "+tried this already\n",
    }


def test_dispatch_embeds_family_evidence(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    ctx = _ctx(recent_events=[_family_fail_event()])
    result = asyncio.run(dispatch_phase(ctx))
    prompt = result["dispatch_prompt"]
    assert "## Evidence Pack" in prompt
    assert "evt_fail_prior" in prompt
    assert "Already-tried edit fingerprints" in prompt
    # Structured pack exposed for observability.
    assert result["evidence_pack"]["rejected"] == 1
    assert result["evidence_pack"]["attempts"][0]["gene_id"] == "g1"
    # Evidence precedes the Selected Gene suggestion.
    assert prompt.index("## Evidence Pack") < prompt.index("## Selected Gene")
    capsys.readouterr()


def test_dispatch_novel_family_has_no_section(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    unrelated = {
        "id": "evt_other",
        "outcome": {"status": "failed"},
        "signals": ["mypy_error"],
    }
    result = asyncio.run(dispatch_phase(_ctx(recent_events=[unrelated])))
    assert "## Evidence Pack" not in result["dispatch_prompt"]
    assert result["evidence_pack"]["attempts"] == []
    capsys.readouterr()


def test_dispatch_reads_event_store_when_ctx_empty(
    _ws: Path, capsys: pytest.CaptureFixture
) -> None:
    from evolver.gep.asset_store import append_event_jsonl

    append_event_jsonl(_family_fail_event())
    result = asyncio.run(dispatch_phase(_ctx()))  # no recent_events in ctx
    assert "evt_fail_prior" in result["dispatch_prompt"]
    capsys.readouterr()


def test_dispatch_evidence_failure_never_aborts(
    _ws: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import evolver.gep.evidence_pack as ep

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("pack boom")

    monkeypatch.setattr(ep, "build_evidence_pack", boom)
    result = asyncio.run(dispatch_phase(_ctx(recent_events=[_family_fail_event()])))
    assert result.get("dispatch_prompt"), "dispatch must survive evidence failure"
    assert result.get("evidence_pack_error")
    capsys.readouterr()


def test_prompt_artifact_carries_evidence(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    from evolver.gep.paths import get_evolution_dir

    result = asyncio.run(dispatch_phase(_ctx(recent_events=[_family_fail_event()])))
    artifact = get_evolution_dir() / "last_prompt.md"
    text = artifact.read_text(encoding="utf-8")
    assert "## Evidence Pack" in text
    assert json.dumps(result["evidence_pack"]["digests"])  # digests recorded
    capsys.readouterr()
