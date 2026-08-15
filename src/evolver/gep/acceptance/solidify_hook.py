"""Acceptance-gate hook for the ``solidify`` process.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint A1).

This module is the single integration seam between :func:`evolver.gep.solidify`
and the acceptance gate. It runs the T0 tier (degraded T0-only when B1 is
disabled — no ``held_in`` source), persists the new baseline when the state
improves, and returns the :class:`AcceptanceResult` for solidify to act on
(rollback + record-failure on reject; attach to the event on accept).

Process boundary (constraint C-1): solidify runs in a separate process from
the cycle. The gate reads the last-known-good T0 baseline from disk and
discovers the current test set afresh; the B1 diagnosis artifact (when B1 is
enabled) is referenced via ``last_run["diagnosis_ref"]`` for the future
held_in/T2 layers. For T0-only mode, ``diagnosis_ref`` may be absent.
"""

from __future__ import annotations

from typing import Any

from evolver.config import ACCEPTANCE_DELTA_EPSILON, ACCEPTANCE_REPEATS
from evolver.gep.acceptance.orchestrator import (
    load_baseline_payload,
    run_acceptance_gate,
    save_baseline,
)
from evolver.gep.acceptance.schemas import AcceptanceResult
from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_gep_assets_dir


def _baseline_path() -> Any:
    return get_gep_assets_dir() / "acceptance" / "baseline.json"


def _snapshot_dir() -> Any:
    return get_gep_assets_dir() / "acceptance" / "snapshots"


def gate_for_solidify(
    _last_run: dict[str, Any],
    cwd: Any,
) -> AcceptanceResult | None:
    """Run the acceptance gate during solidify.

    Returns ``None`` when the gate is disabled (regression: solidify behaves
    exactly as before). Otherwise returns the :class:`AcceptanceResult`; the
    caller (solidify) rolls back on ``not accepted`` and records the result on
    the event otherwise.

    ``_last_run`` is currently unused in T0-only mode; the held_in / T2 layers
    (later sprints) consume ``_last_run["diagnosis_ref"]`` (constraint C-1) to
    read the B1 causal artifact across the process boundary.

    Baseline persistence: the new T0 rate is saved only when the gate
    *establishes* (first run) or the T0 verdict is ``improved`` — never on
    ``unchanged`` (prevents epsilon-erosion across cycles) and never on reject.
    """
    if not is_enabled("enable_acceptance_gate"):
        return None

    baseline_path = _baseline_path()
    snapshot_dir = _snapshot_dir()
    baseline_payload = load_baseline_payload(baseline_path)
    baseline = baseline_payload.get("t0_pass_rate") if baseline_payload else None

    result = run_acceptance_gate(
        cwd=cwd,
        snapshot_dir=snapshot_dir,
        baseline_t0_rate=baseline,
        repeats=ACCEPTANCE_REPEATS,
        epsilon=ACCEPTANCE_DELTA_EPSILON,
        baseline_t0_snapshot=(
            baseline_payload.get("t0_snapshot_hash") if baseline_payload else None
        ),
    )

    if result.accepted:
        t0_layer = next(
            (layer for layer in result.layers if layer.kind == "T0_frozen"),
            None,
        )
        should_persist = (
            t0_layer is not None
            and (result.reason == "t0_baseline_established" or t0_layer.verdict == "improved")
            and t0_layer.candidate_mean > 0
        )
        if should_persist and t0_layer is not None:
            save_baseline(
                baseline_path,
                t0_layer.candidate_mean,
                t0_layer.layer_id,
            )
    return result


def gate_or_none(last_run: dict[str, Any], cwd: Any) -> AcceptanceResult | None:
    """Safe wrapper for solidify: run the gate, never raise.

    Any gate-side failure degrades to ``None`` (gate disabled semantics) so
    the core solidify path can never be broken by the opt-in enhancement.
    """
    try:
        return gate_for_solidify(last_run, cwd)
    except Exception as exc:
        print(f"[solidify] acceptance gate error: {exc}")
        return None


__all__ = ["gate_for_solidify", "gate_or_none"]
