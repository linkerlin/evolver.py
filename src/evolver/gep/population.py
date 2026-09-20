"""Population orchestration — K=2 candidate search over eval worktrees.

RSI P1-3 second half (round-41), Darwin Gödel Machine population semantics:
each round used to be a single-candidate greedy search; this module evaluates
N mechanical proposals (S29 channel) in FRESH worktrees (S26.5 bridge),
adjudicates under a budget guard, and hands the WINNER to the normal frozen
solidify path — the acceptance gate and anchor still judge the final landing,
so population selection ADDS a pre-stage without touching frozen rejection
semantics. Losers are archived as variants (round-40) with ``sibling_of``
lineage: 暂弱变体可成垫脚石.

Budget guard: population search costs ~Kx a single cascade (round-38 K=2
projection: median +264s/cycle). POPULATION_BUDGET_S caps the whole search;
candidates not started before the cap are skipped and RECORDED as
``budget_skipped`` — degrading to K=1 is honest, silent truncation is not.
"""

from __future__ import annotations

import logging
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from evolver.gep.git_ops import run_cmd
from evolver.gep.proposal import apply_proposal, parse_proposal

logger = logging.getLogger(__name__)

#: Wall-clock ceiling for the whole population search. Two full cascades at
#: their per-stage timeout budget plus margin; module constant (no env knob —
#: soak charter). Exceeded → remaining candidates are skipped, not truncated.
POPULATION_BUDGET_S: Final = 1500.0


@dataclass
class CandidateResult:
    """One candidate's population-stage outcome (cascade pre-selection)."""

    index: int
    proposal_path: str
    applied: bool
    overall_ok: bool
    score: float
    files_touched: int
    duration_ms: int
    status: str  # accepted | rejected | budget_skipped | apply_failed
    detail: dict[str, Any] = field(default_factory=dict)


def _fresh_worktree(src: Path) -> tuple[Path, Callable[[], None]]:
    """Worktree at HEAD WITHOUT overlaying the live tree's mutation."""
    dest = Path(tempfile.gettempdir()) / f"evolver-pop-{uuid.uuid4().hex[:12]}"
    run_cmd(["worktree", "add", "--detach", str(dest), "HEAD"], cwd=src)

    def _cleanup() -> None:
        try:
            run_cmd(["worktree", "remove", "--force", str(dest)], cwd=src)
        except Exception:
            logger.warning("[population] worktree cleanup failed for %s", dest)

    return dest, _cleanup


def evaluate_candidate(
    proposal_path: Path,
    src: Path,
    *,
    cascade_commands: list[Any],
    last_run: dict[str, Any] | None = None,
) -> CandidateResult:
    """Apply *proposal_path* in a fresh worktree and run the cascade there.

    The acceptance gate / anchor do NOT run here: they judge the final
    landing (the winner still goes through the frozen solidify path).
    """
    from evolver.gep.solidify import _run_validations

    del last_run  # reserved for gate integration; cascade-only for v1
    worktree, cleanup = _fresh_worktree(src)
    t0 = time.monotonic()
    try:
        try:
            proposal = parse_proposal(_read_proposal(proposal_path))
            applied = apply_proposal(proposal, worktree)
        except ValueError as exc:
            # apply_proposal raises on hallucinated anchors / bad shapes —
            # that is an apply failure, not a validation verdict.
            return CandidateResult(
                index=-1,
                proposal_path=str(proposal_path),
                applied=False,
                overall_ok=False,
                score=0.0,
                files_touched=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="apply_failed",
                detail={"error": str(exc)[:300]},
            )
        if not applied.get("applied", False):
            return CandidateResult(
                index=-1,
                proposal_path=str(proposal_path),
                applied=False,
                overall_ok=False,
                score=0.0,
                files_touched=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="apply_failed",
                detail=applied,
            )
        changed = run_cmd(["status", "--porcelain"], cwd=worktree)
        files_touched = len([ln for ln in changed.splitlines() if ln.strip()])
        result = _run_validations(cascade_commands, worktree, cascade=True)
        stages = result.get("results") or []
        passed = sum(1 for s in stages if s.get("ok"))
        score = round(passed / len(stages), 4) if stages else 0.0
        ok = bool(result.get("ok"))
        return CandidateResult(
            index=-1,
            proposal_path=str(proposal_path),
            applied=True,
            overall_ok=ok,
            score=score,
            files_touched=files_touched,
            duration_ms=int(result.get("duration_ms") or 0),
            status="accepted" if ok else "rejected",
            detail={"validation": result},
        )
    finally:
        cleanup()


def _read_proposal(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def adjudicate(results: list[CandidateResult]) -> CandidateResult | None:
    """Pick the winner; None when no candidate is admissible.

    Rule (frozen by anchor epoch 11): accepted beats everything; among
    accepted — higher cascade score, then FEWER files touched (smaller
    reversible patch wins), then lower index (stable, deterministic). Ties
    are impossible to observe externally because the index tiebreak is total.
    """
    admissible = [r for r in results if r.status == "accepted"]
    if not admissible:
        return None
    return sorted(
        admissible,
        key=lambda r: (-r.score, r.files_touched, r.index),
    )[0]


def run_population(
    proposal_paths: list[Path],
    src: Path,
    *,
    cascade_commands: list[Any],
    budget_s: float = POPULATION_BUDGET_S,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Evaluate candidates under the budget guard; return the judgment record.

    A candidate whose start time would exceed *budget_s* (measured from the
    search's first tick) is marked ``budget_skipped`` — population search
    degrades to fewer candidates visibly, never silently.
    """
    start = now()
    results: list[CandidateResult] = []
    for index, path in enumerate(proposal_paths):
        if now() - start > budget_s:
            results.append(
                CandidateResult(
                    index=index,
                    proposal_path=str(path),
                    applied=False,
                    overall_ok=False,
                    score=0.0,
                    files_touched=0,
                    duration_ms=0,
                    status="budget_skipped",
                )
            )
            continue
        result = evaluate_candidate(path, src, cascade_commands=cascade_commands)
        result.index = index
        results.append(result)
    winner = adjudicate(results)
    return {
        "candidates": [r.__dict__ for r in results],
        "winner": winner.proposal_path if winner else None,
        "winner_index": winner.index if winner else None,
        "budget_s": budget_s,
        "elapsed_s": round(now() - start, 3),
        "adjudication": (
            "accepted > rejected; score desc; files asc; index asc"
            if winner
            else "no admissible candidate"
        ),
    }


__all__ = [
    "POPULATION_BUDGET_S",
    "CandidateResult",
    "adjudicate",
    "evaluate_candidate",
    "run_population",
]
