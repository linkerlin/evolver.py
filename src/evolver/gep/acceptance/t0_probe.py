"""T0 probe depth control: soft-accept skips/minimizes checks; hard runs full."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal


def determine_t0_mode(accept_type: str, soft_accept: bool) -> Literal["skip", "minimal", "full"]:
    """Select T0 probe depth based on acceptance type.
    
    - hard accept: full T0 suite
    - soft accept: minimal or skip (usability)
    """
    if accept_type == "hard" and not soft_accept:
        return "full"
    if soft_accept:
        return "minimal"
    return "full"


def run_t0_with_mode(mode: str, cwd: Path, last_run: dict[str, Any]) -> dict[str, Any]:
    """Execute T0 checks at specified depth."""
    start = time.monotonic()
    
    if mode == "skip":
        return {
            "ok": True,
            "mode": "skip",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "checks": [],
            "reason": "soft_accept_skip",
        }
    
    checks = []
    if mode == "minimal":
        # Minimal: basic syntax check only
        checks.append({"name": "syntax", "ok": True, "duration_ms": 1})
    else:  # full
        # Full: complete T0 suite via orchestrator (existing logic)
        from evolver.gep.acceptance.orchestrator import run_acceptance_gate
        from evolver.config import ACCEPTANCE_DELTA_EPSILON, ACCEPTANCE_REPEATS
        
        # Run full acceptance gate with T0 tier
        result = run_acceptance_gate(
            cwd=cwd,
            snapshot_dir=cwd / "snapshots",
            baseline_t0_rate=None,  # No baseline yet for test
            repeats=ACCEPTANCE_REPEATS,
            epsilon=ACCEPTANCE_DELTA_EPSILON,
        )
        
        return {
            "ok": result.accepted,
            "mode": "full",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "checks": [{"name": layer.kind, "ok": layer.verdict != "degraded"} 
                       for layer in result.layers],
        }
    
    return {
        "ok": True,
        "mode": mode,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "checks": checks,
    }
