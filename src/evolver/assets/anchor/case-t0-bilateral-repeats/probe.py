"""Anchor probe: T0 bilateral repeats (RSI P0-2, 演进方案.md §11.4).

The acceptance gate previously synthesized a single baseline observation from a
scalar float (orchestrator.py:221), while candidate repeats enjoyed multi-run
sampling and mode-based flake adjudication. This created asymmetric gating:
a lucky low baseline could falsely accept regressed candidates, while an
unlucky high baseline could falsely kill valid mutations.

This probe freezes out-of-tree invariants for bilateral repeats:
1. Round-trip persistence: save_baseline preserves multi-repeat observations and
   adjudication metadata; load_baseline_repeats reconstructs them faithfully.
2. Gating symmetry: when baseline_repeats is supplied, the resulting T0
   LayerMetric preserves the multi-repeat observations rather than collapsing
   to a single synthetic element.
3. Backward compatibility: legacy single-float baseline payloads degrade
   gracefully without crashing.

Exit 0 = pass.
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


def _check_persistence_roundtrip(ws: Path) -> None:
    from evolver.gep.acceptance.orchestrator import (
        load_baseline,
        load_baseline_payload,
        load_baseline_repeats,
        save_baseline,
    )
    from evolver.gep.acceptance.schemas import RepeatObs

    p = ws / "baseline.json"
    repeats = [
        RepeatObs(repeat_index=0, score=0.8, denominator=5),
        RepeatObs(repeat_index=1, score=0.8, denominator=5),
    ]
    adj = {"majority_score": 0.8, "counts": {"0.8": 2}}

    save_baseline(p, t0_pass_rate=0.8, snapshot_hash="snap_abc", repeats=repeats, adjudication=adj)

    assert load_baseline(p) == 0.8, f"scalar rate mismatch: {load_baseline(p)}"
    payload = load_baseline_payload(p)
    assert payload is not None, "payload must not be None"
    assert payload.get("t0_snapshot_hash") == "snap_abc", "snapshot hash mismatch"
    assert payload.get("t0_adjudication") == adj, "adjudication metadata mismatch"

    loaded_repeats = load_baseline_repeats(p)
    assert loaded_repeats is not None, "loaded repeats must not be None"
    assert len(loaded_repeats) == 2, f"expected 2 repeats, got {len(loaded_repeats)}"
    assert loaded_repeats[0].score == 0.8 and loaded_repeats[0].denominator == 5
    assert loaded_repeats[1].repeat_index == 1


def _check_gating_preserves_bilateral_repeats(ws: Path) -> None:
    from evolver.gep.acceptance import t0_frozen
    from evolver.gep.acceptance.orchestrator import run_acceptance_gate
    from evolver.gep.acceptance.schemas import RepeatObs

    # Stub t0_frozen so probe runs without subprocess overhead
    frozen_ids = [f"test_{i}" for i in range(4)]
    t0_frozen.discover_test_ids = lambda _cwd: list(frozen_ids)  # type: ignore[assignment]
    t0_frozen.run_pass_rate = lambda ids, _cwd, **_kw: (3, len(ids))  # type: ignore[assignment]
    t0_frozen.freeze_snapshot = lambda _ids, d: d / "snap.txt"  # type: ignore[assignment]
    t0_frozen.load_snapshot = lambda _p: list(frozen_ids)  # type: ignore[assignment]

    base_obs = [
        RepeatObs(repeat_index=0, score=0.75, denominator=4),
        RepeatObs(repeat_index=1, score=0.75, denominator=4),
    ]

    result = run_acceptance_gate(
        cwd=ws,
        snapshot_dir=ws / "snaps",
        baseline_t0_rate=0.75,
        baseline_repeats=base_obs,
        repeats=2,
    )
    assert result.accepted is True, "expected accept on parity rate"
    layer = result.layers[0]
    assert len(layer.baseline_repeats) == 2, (
        f"expected 2 baseline repeats, got {len(layer.baseline_repeats)}"
    )
    assert layer.baseline_mean == 0.75, f"expected 0.75 baseline mean, got {layer.baseline_mean}"


def _check_legacy_fallback(ws: Path) -> None:
    from evolver.gep.acceptance.orchestrator import run_acceptance_gate

    # No baseline_repeats supplied, legacy scalar rate only
    result = run_acceptance_gate(
        cwd=ws,
        snapshot_dir=ws / "snaps",
        baseline_t0_rate=0.5,
        baseline_repeats=None,
        repeats=1,
    )
    assert result.accepted is True
    layer = result.layers[0]
    assert len(layer.baseline_repeats) == 1, "legacy fallback should have 1 synthetic repeat"
    assert layer.baseline_mean == 0.5


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anchor-t0-bilateral-") as td:
        ws = Path(td)
        _isolate(ws)
        _check_persistence_roundtrip(ws)
        _check_gating_preserves_bilateral_repeats(ws)
        _check_legacy_fallback(ws)
    print("PASS: case-t0-bilateral-repeats invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
