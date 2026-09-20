"""Anchor probe: population adjudication invariants (round-41, RSI P1-3).

The population pre-stage decides WHICH candidate reaches the frozen landing
path — that selection authority is frozen here out-of-tree: (a) accepted
beats rejected, no rejected candidate can win; (b) the tiebreak is total and
deterministic (score desc, files asc, index asc); (c) the budget guard skips
candidates VISIBLY (budget_skipped status), never silently truncates the
search; (d) the winner still owes the frozen path its verdict — population
acceptance alone lands nothing. Pure in-process checks. Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


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


def _result(
    index: int,
    status: str,
    score: float = 0.0,
    files: int = 0,
) -> object:
    from evolver.gep.population import CandidateResult

    return CandidateResult(
        index=index,
        proposal_path=f"p{index}",
        applied=status != "budget_skipped",
        overall_ok=status == "accepted",
        score=score,
        files_touched=files,
        duration_ms=1,
        status=status,
    )


def _check() -> None:
    from evolver.gep.population import POPULATION_BUDGET_S, adjudicate, run_population

    # (a) accepted beats rejected regardless of score ordering.
    winner = adjudicate([_result(0, "rejected", score=1.0), _result(1, "accepted", score=0.5)])
    assert winner is not None and winner.index == 1, "accepted must beat rejected"

    # (b) deterministic total tiebreak: score desc, files asc, index asc.
    w2 = adjudicate(
        [
            _result(0, "accepted", score=0.9, files=5),
            _result(1, "accepted", score=0.9, files=3),
            _result(2, "accepted", score=1.0, files=9),
        ]
    )
    assert w2.index == 2, f"higher score wins first: {w2.index}"
    w3 = adjudicate(
        [_result(0, "accepted", score=0.9, files=5), _result(1, "accepted", score=0.9, files=3)]
    )
    assert w3.index == 1, f"fewer files wins on score tie: {w3.index}"
    w4 = adjudicate(
        [_result(5, "accepted", score=0.9, files=3), _result(2, "accepted", score=0.9, files=3)]
    )
    assert w4.index == 2, f"lower index wins total tie: {w4.index}"

    # No admissible candidate → None (population acceptance lands nothing).
    assert adjudicate([_result(0, "rejected"), _result(1, "budget_skipped")]) is None

    # (c) budget guard skips VISIBLY: with an exhausted clock the remaining
    # candidate is marked budget_skipped, not dropped from the record.
    clock = {"t": 0.0}

    def fake_now() -> float:
        clock["t"] += POPULATION_BUDGET_S + 1
        return clock["t"]

    judgment = run_population(
        [Path("a.json"), Path("b.json")],
        Path("."),
        cascade_commands=[],
        budget_s=POPULATION_BUDGET_S,
        now=fake_now,
    )
    statuses = [c["status"] for c in judgment["candidates"]]
    assert "budget_skipped" in statuses, statuses
    assert len(judgment["candidates"]) == 2, "skip must be recorded, not truncated"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: population adjudication invariant violated: {exc}")
            return 1
        print("PASS: accepted-beats-rejected, total tiebreak, visible budget skip")
        return 0


if __name__ == "__main__":
    sys.exit(main())
