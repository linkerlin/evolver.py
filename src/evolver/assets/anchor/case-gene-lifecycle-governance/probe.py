"""Anchor probe: gene lifecycle governance (RSI P1-5, round-33).

Library Drift mitigation is selection machinery: if a future mutation makes
retirement unreachable (or makes retired genes selectable again), the in-repo
tests that used to catch it could be weakened alongside. This probe freezes
the load-bearing invariants out-of-tree:

1. zero-work evidence (>= N evaluable landings, zero resolutions) reaches
   ``under_review``;
2. a re-trial during review that still produces nothing reaches ``retired``;
3. a resolution during the review window revalidates back to ``active``
   (retirement is falsifiable, not a time bomb);
4. retired genes are excluded from selection even as the best lexical match,
   and a retired-only pool yields no selection (the engine mutates instead of
   re-running a known-dead gene);
5. declared ``applicability.signal_families`` hard-gates retrieval.

The checked functions are pure (no file writes; the selector reads env only),
so the probe isolates the engine env and asserts in-process. Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from evolver.gep.gene_lifecycle import evaluate_gene_lifecycle, landing_stats
from evolver.gep.selector import select_gene


def _isolate(ws: Path) -> None:
    (ws / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "OPENCLAW_WORKSPACE": str(ws),
            "EVOLVER_REPO_ROOT": str(ws),
            "EVOLVER_NO_PARENT_GIT": "1",
            "MEMORY_DIR": str(ws / "memory"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
            "EVOLVER_HOME": str(ws / ".evomap"),
            "EVOLVER_SETTINGS_DIR": str(ws / ".evolver_settings"),
            "EVOLVER_LOGS_DIR": str(ws / "logs"),
        }
    )


def _landing(gene: str, i: int) -> dict[str, object]:
    return {
        "id": f"land_{gene}_{i}",
        "outcome": {"status": "success"},
        "mutation": {"landed_gene_ids": [gene]},
        "signals": ["log_error"],
    }


def _failure(i: int) -> dict[str, object]:
    return {"id": f"fail_{i}", "outcome": {"status": "failed"}, "signals": ["log_error"]}


def _resolution(i: int) -> dict[str, object]:
    return {"id": f"ok_{i}", "outcome": {"status": "success"}, "signals": ["hub_offline"]}


def _zero_work_history(gene: str = "gene_dead") -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for i in range(3):
        events.append(_landing(gene, i))
        events.append(_failure(i))
    # Padding so the last landing has observed descendants too.
    events.extend(_resolution(100 + i) for i in range(5))
    return events


def _check_lifecycle() -> None:
    # --- Invariant 1: zero-work evidence reaches under_review ---
    events = _zero_work_history()
    stats = landing_stats(events)
    assert stats["gene_dead"]["observations"] == 3, stats
    assert stats["gene_dead"]["resolved"] == 0, stats
    transitions = evaluate_gene_lifecycle(events, {})
    assert len(transitions) == 1, transitions
    t0 = transitions[0]
    assert (t0.gene_id, t0.to_status, t0.reason) == (
        "gene_dead",
        "under_review",
        "zero_work_evidence",
    ), t0

    # --- Invariant 2: re-tried during review, still zero-work -> retired ---
    from evolver.gep.gene_lifecycle import GeneLifecycleRecord

    review_state = {
        "gene_dead": GeneLifecycleRecord(
            gene_id="gene_dead",
            status="under_review",
            evidence={"observations_at_review": 3, "resolved_at_review": 0},
        )
    }
    events_retried = [*events, _landing("gene_dead", 9), _failure(9), *_resolution_pad()]
    transitions = evaluate_gene_lifecycle(events_retried, review_state)
    assert len(transitions) == 1, transitions
    assert transitions[0].to_status == "retired", transitions[0]
    assert transitions[0].reason == "zero_work_after_review", transitions[0]

    # --- Invariant 3: a resolution during review revalidates to active ---
    events_ok = [*events, _landing("gene_dead", 9), _resolution(9), *_resolution_pad()]
    transitions = evaluate_gene_lifecycle(events_ok, review_state)
    assert len(transitions) == 1, transitions
    assert transitions[0].to_status == "active", transitions[0]
    assert transitions[0].reason == "revalidated", transitions[0]

    # --- Invariant 4: retired is terminal for the engine ---
    retired_state = {
        "gene_dead": GeneLifecycleRecord(
            gene_id="gene_dead",
            status="retired",
            evidence={"observations_at_review": 3, "resolved_at_review": 0},
        )
    }
    assert evaluate_gene_lifecycle(events_ok, retired_state) == [], "retired must not self-revive"


def _resolution_pad() -> list[dict[str, object]]:
    return [_resolution(200 + i) for i in range(5)]


def _check_selector() -> None:
    gene_dead = {"id": "gene_dead", "category": "repair", "signals_match": ["log_error"]}
    gene_live = {"id": "gene_live", "category": "repair", "signals_match": ["log_error"]}

    # --- Invariant 4 (selection): retired excluded even as top match ---
    picked = select_gene([gene_dead, gene_live], ["log_error"], {"retiredGeneIds": {"gene_dead"}})
    assert picked["selected"] is not None, picked
    assert picked["selected"]["id"] == "gene_live", picked
    only_dead = select_gene([gene_dead], ["log_error"], {"retiredGeneIds": {"gene_dead"}})
    assert only_dead["selected"] is None, only_dead

    # --- Review window stays selectable (penalty, not ban) ---
    review_pick = select_gene([gene_dead], ["log_error"], {"underReviewGeneIds": {"gene_dead"}})
    assert review_pick["selected"] is not None, review_pick
    assert review_pick["selected"]["id"] == "gene_dead", review_pick

    # --- Invariant 5: declared applicability families hard-gate retrieval ---
    scoped = {
        "id": "gene_scoped",
        "category": "repair",
        "signals_match": ["log_error", "mypy_error"],
        "applicability": {"signal_families": ["mypy_error"]},
    }
    assert select_gene([scoped], ["log_error"])["selected"] is None, "family gate must exclude"
    matched = select_gene([scoped], ["mypy_error"])
    assert matched["selected"] is not None and matched["selected"]["id"] == "gene_scoped", matched


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check_lifecycle()
            _check_selector()
        except AssertionError as exc:
            print(f"FAIL: gene lifecycle invariant violated: {exc}")
            return 1
        print(
            "PASS: review/retire reachable, retired unselectable, revalidation live, "
            "applicability gate enforced"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
