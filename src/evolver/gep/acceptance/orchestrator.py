"""Acceptance-gate orchestrator: assemble layers and decide.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint A1).

Ties the T0 tier (:mod:`evolver.gep.acceptance.t0_frozen`) to the decision
rule (:func:`evolver.gep.acceptance.gate.decide`). The *baseline* T0 pass rate
is the last-accepted state's rate (persisted by the caller across cycles), so
the gate compares "did this mutation regress the frozen test set vs. the last
known-good state". First run (no baseline yet) establishes the baseline
without gating.

T1/T2 tiers are added here once Sprint B2/B1 wire them; for T0-only mode the
gate degrades to a pure regression floor (constraint C-1: solidify may run
with B1 disabled).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.gep.acceptance import t0_frozen
from evolver.gep.acceptance.gate import classify_rate, decide
from evolver.gep.acceptance.schemas import (
    AcceptanceResult,
    LayerMetric,
    RepeatObs,
)

_BASELINE_FORMAT = "evolver.acceptance_baseline.v0"


def load_baseline(path: Path) -> float | None:
    """Read the persisted last-known-good T0 pass rate (or None if absent)."""
    payload = load_baseline_payload(path)
    rate = payload.get("t0_pass_rate") if payload else None
    return float(rate) if isinstance(rate, (int, float)) else None


def load_baseline_payload(path: Path) -> dict[str, object] | None:
    """Read the full baseline record (rate + snapshot hash), None if absent."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_baseline(
    path: Path,
    t0_pass_rate: float,
    snapshot_hash: str,
    *,
    repeats: list[RepeatObs] | None = None,
    adjudication: dict[str, Any] | None = None,
) -> None:
    """Persist the new last-known-good T0 rate + snapshot hash + bilateral repeat observations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "format": _BASELINE_FORMAT,
        "t0_pass_rate": t0_pass_rate,
        "t0_snapshot_hash": snapshot_hash,
    }
    if repeats is not None:
        payload["t0_repeats"] = [r.model_dump() for r in repeats]
    if adjudication is not None:
        payload["t0_adjudication"] = adjudication
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_baseline_repeats(path: Path) -> list[RepeatObs] | None:
    """Read persisted repeat observations of the baseline, None if absent or corrupt."""
    payload = load_baseline_payload(path)
    if not payload:
        return None
    raw = payload.get("t0_repeats")
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [RepeatObs(**r) for r in raw if isinstance(r, dict)]
    except Exception:
        return None


def _t0_layer_id(snap_label: str) -> str:
    """Canonical T0 layer id: ``T0_frozen@<hash>``.

    The label arrives in two spellings: a snapshot stem (``t0_<hash>``,
    from freeze_snapshot) or the persisted baseline value — which
    solidify_hook stores as the previous run's full layer id
    (``T0_frozen@<hash>``). Stripping only ``t0_`` let the stored
    ``T0_frozen@`` through and doubled the prefix on every comparison
    cycle (round-21: live events read ``T0_frozen@T0_frozen@<hash>``).
    """
    core = snap_label.removeprefix("T0_frozen@").removeprefix("t0_")
    return f"T0_frozen@{core}"


def _run_t0_repeats(
    frozen_ids: list[str],
    cwd: Path,
    *,
    repeats: int,
) -> list[RepeatObs]:
    """Run the frozen T0 set *repeats* times; return per-repeat observations."""
    total = len(frozen_ids)
    obs: list[RepeatObs] = []
    for index in range(max(1, repeats)):
        passed, _total = t0_frozen.run_pass_rate(frozen_ids, cwd)
        rate = (passed / total) if total else 0.0
        obs.append(RepeatObs(repeat_index=index, score=rate, denominator=total))
    return obs


def _adjudicate_flakes(
    frozen_ids: list[str],
    cwd: Path,
    obs: list[RepeatObs],
) -> tuple[list[RepeatObs], dict[str, Any] | None]:
    """Round-25 granularity-aware flake adjudication for T0 repeats.

    The frozen set is deterministic — same IDs, same tree, so repeats SHOULD
    be identical. Any inter-repeat difference is measurement noise (a timed-
    out chunk once flaked a repeat to 0.886, DEBUG #32; a single-test flake
    later dragged the mean by exactly 1/3519, DEBUG #35 tail). Trigger on ANY
    mismatch (no spread threshold — a fixed 0.05 bar let single-test noise
    through), run ONE extra adjudication repeat, and anchor on the majority
    value: observations equal to the mode are kept, the rest are recorded in
    ``adjudication`` but excluded from the mean. No majority (all distinct =
    continuous flakiness) keeps everything — conservative, fail-toward-
    reject. Identical repeats (real regression or real health) never trigger
    adjudication; the rejection path is untouched.
    """
    if len(obs) < 2:
        return obs, None
    scores = [o.score for o in obs]
    if max(scores) == min(scores):
        return obs, None
    extra = _run_t0_repeats(frozen_ids, cwd, repeats=1)[0]
    extra = extra.model_copy(update={"repeat_index": max(o.repeat_index for o in obs) + 1})
    all_obs = [*obs, extra]
    scores = [o.score for o in all_obs]
    counts: dict[float, int] = {}
    for s in scores:
        counts[s] = counts.get(s, 0) + 1
    majority_score, majority_count = max(counts.items(), key=lambda kv: kv[1])
    if majority_count < 2:
        # all distinct — too flaky to adjudicate; keep everything and say so
        info: dict[str, Any] = {
            "trigger": "repeat_mismatch",
            "spread": round(max(scores) - min(scores), 6),
            "adjudication_repeat": extra.model_dump(),
            "counts": {str(k): v for k, v in counts.items()},
            "trimmed": [],
            "reason": (
                "repeats mismatched and the adjudication repeat produced a "
                "third value — continuous flakiness, all observations kept "
                "(conservative: verdict uses the full mean)"
            ),
        }
        return all_obs, info
    kept = [o for o in all_obs if o.score == majority_score]
    info = {
        "trigger": "repeat_mismatch",
        "spread": round(max(scores) - min(scores), 6),
        "adjudication_repeat": extra.model_dump(),
        "counts": {str(k): v for k, v in counts.items()},
        "majority_score": round(majority_score, 6),
        "trimmed": [o.model_dump() for o in all_obs if o.score != majority_score],
        "reason": (
            "deterministic suite, mismatched repeats; one extra repeat run, "
            "majority value anchored, minority observations excluded from "
            "the mean (recorded, not hidden) — measurement noise must not "
            "become a verdict"
        ),
    }
    return kept, info


def run_acceptance_gate(
    *,
    cwd: Path,
    snapshot_dir: Path,
    baseline_t0_rate: float | None,
    repeats: int = 2,
    epsilon: float = 0.0,
    strict_t2: bool = False,
    baseline_t0_snapshot: str | None = None,
    baseline_repeats: list[RepeatObs] | None = None,
    baseline_cwd: Path | None = None,
) -> AcceptanceResult:
    """Run the gate. Returns the :class:`AcceptanceResult`.

    *baseline_t0_rate* ``None`` → first run, establishes baseline (accepts
    without gating; caller persists the candidate rate). T0-only degraded mode:
    the gate accepts iff T0 did not regress. (The ``held_in`` layer is attached
    by a later increment once Sprint B1/B2 wire it.)

    Bilateral repeats (RSI P0-2): when *baseline_cwd* is provided, the baseline
    is measured live across *repeats* runs with flake adjudication. Otherwise,
    persisted *baseline_repeats* (from previous candidate runs) are used.
    Falls back to a synthetic single observation from *baseline_t0_rate*.

    Soak fix: with a baseline present, the frozen ID set is loaded from the
    BASELINE snapshot (``t0_snapshot_hash``), not re-derived from the current
    tree — re-freezing made deleted tests vanish from the denominator and the
    gate blind to test deletion (soak round 3). Falls back to discovery when
    the baseline snapshot is missing.
    """
    frozen: list[str] = []
    snap_label = ""
    if baseline_t0_rate is not None and baseline_t0_snapshot:
        snap_hash = baseline_t0_snapshot.split("@")[-1]
        frozen = t0_frozen.load_snapshot(snapshot_dir / f"t0_{snap_hash}.txt")
        snap_label = baseline_t0_snapshot
    if not frozen:
        test_ids = t0_frozen.discover_test_ids(cwd)
        snap = t0_frozen.freeze_snapshot(test_ids, snapshot_dir)
        frozen = t0_frozen.load_snapshot(snap)
        snap_label = snap.stem
    candidate_repeats, adjudication = _adjudicate_flakes(
        frozen, cwd, _run_t0_repeats(frozen, cwd, repeats=repeats)
    )

    if baseline_t0_rate is None and baseline_repeats is None and baseline_cwd is None:
        # Establishing mode: record only, no gating. A flake here would poison
        # the baseline low (everything after would read "improved"), so
        # adjudication applies before the rate is recorded/persisted.
        total = len(frozen)
        t0_layer = LayerMetric(
            layer_id=_t0_layer_id(snap_label),
            kind="T0_frozen",
            baseline_repeats=[],
            candidate_repeats=candidate_repeats,
            baseline_mean=0.0,
            candidate_mean=candidate_repeats[0].score if candidate_repeats else 0.0,
            delta=0.0,
            verdict="unchanged",
            adjudication=adjudication,
        )
        return AcceptanceResult(
            accepted=True,
            layers=[t0_layer],
            reason="t0_baseline_established",
            repeats=repeats,
        )

    total = len(frozen)
    base_adjudication: dict[str, Any] | None = None
    if baseline_cwd is not None and baseline_cwd.is_dir():
        base_obs, base_adjudication = _adjudicate_flakes(
            frozen, baseline_cwd, _run_t0_repeats(frozen, baseline_cwd, repeats=repeats)
        )
    elif baseline_repeats is not None and len(baseline_repeats) > 0:
        base_obs = baseline_repeats
    elif baseline_t0_rate is not None:
        base_obs = [RepeatObs(repeat_index=0, score=baseline_t0_rate, denominator=total)]
    else:
        base_obs = []

    b_mean, c_mean, delta, verdict = classify_rate(base_obs, candidate_repeats, epsilon=epsilon)
    t0_layer = LayerMetric(
        layer_id=_t0_layer_id(snap_label),
        kind="T0_frozen",
        baseline_repeats=base_obs,
        candidate_repeats=candidate_repeats,
        baseline_mean=b_mean,
        candidate_mean=c_mean,
        delta=delta,
        verdict=verdict,
        adjudication=adjudication or base_adjudication,
    )

    layers: list[LayerMetric] = [t0_layer]
    # held_in / T1 / T2 layers are attached by later sprints; T0-only here.
    result = decide(layers, strict_t2=strict_t2, repeats=repeats)
    return result


__all__ = [
    "load_baseline",
    "load_baseline_payload",
    "load_baseline_repeats",
    "run_acceptance_gate",
    "save_baseline",
]
