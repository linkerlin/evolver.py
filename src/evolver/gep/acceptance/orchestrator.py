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
    return payload.get("t0_pass_rate") if payload else None


def load_baseline_payload(path: Path) -> dict[str, object] | None:
    """Read the full baseline record (rate + snapshot hash), None if absent."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_baseline(path: Path, t0_pass_rate: float, snapshot_hash: str) -> None:
    """Persist the new last-known-good T0 rate + snapshot hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": _BASELINE_FORMAT,
        "t0_pass_rate": t0_pass_rate,
        "t0_snapshot_hash": snapshot_hash,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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


def run_acceptance_gate(
    *,
    cwd: Path,
    snapshot_dir: Path,
    baseline_t0_rate: float | None,
    repeats: int = 2,
    epsilon: float = 0.0,
    strict_t2: bool = False,
    baseline_t0_snapshot: str | None = None,
) -> AcceptanceResult:
    """Run the gate. Returns the :class:`AcceptanceResult`.

    *baseline_t0_rate* ``None`` → first run, establishes baseline (accepts
    without gating; caller persists the candidate rate). T0-only degraded mode:
    the gate accepts iff T0 did not regress. (The ``held_in`` layer is attached
    by a later increment once Sprint B1/B2 wire it.)

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
    candidate_repeats = _run_t0_repeats(frozen, cwd, repeats=repeats)

    if baseline_t0_rate is None:
        # Establishing mode: record only, no gating.
        total = len(frozen)
        t0_layer = LayerMetric(
            layer_id=f"T0_frozen@{snap_label.removeprefix('t0_')}",
            kind="T0_frozen",
            baseline_repeats=[],
            candidate_repeats=candidate_repeats,
            baseline_mean=0.0,
            candidate_mean=candidate_repeats[0].score if candidate_repeats else 0.0,
            delta=0.0,
            verdict="unchanged",
        )
        return AcceptanceResult(
            accepted=True,
            layers=[t0_layer],
            reason="t0_baseline_established",
            repeats=repeats,
        )

    total = len(frozen)
    baseline_repeats = [RepeatObs(repeat_index=0, score=baseline_t0_rate, denominator=total)]
    b_mean, c_mean, delta, verdict = classify_rate(
        baseline_repeats, candidate_repeats, epsilon=epsilon
    )
    t0_layer = LayerMetric(
        layer_id=f"T0_frozen@{snap_label.removeprefix('t0_')}",
        kind="T0_frozen",
        baseline_repeats=baseline_repeats,
        candidate_repeats=candidate_repeats,
        baseline_mean=b_mean,
        candidate_mean=c_mean,
        delta=delta,
        verdict=verdict,
    )

    layers: list[LayerMetric] = [t0_layer]
    # held_in / T1 / T2 layers are attached by later sprints; T0-only here.
    result = decide(layers, strict_t2=strict_t2, repeats=repeats)
    return result


__all__ = [
    "load_baseline",
    "load_baseline_payload",
    "run_acceptance_gate",
    "save_baseline",
]
