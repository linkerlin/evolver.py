"""Diagnosis phase: terminal-cause-first causal attribution of failed events.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint B1).

Sits in the pipeline immediately after ``signals_phase`` and before
``hub_phase``. For each recent *failed* ``EvolutionEvent`` it produces a
:class:`CausalAnalysis` (degraded — all-``unknown`` attribution — until Sprint
D wires a real LLM), then:

* sets ``ctx["causal_brief"]`` (markdown) for the GEP prompt,
* injects ``causal:root_cause:<terminal_cause>`` keys into ``ctx["signals"]``
  (integration constraint **C-4** — select consumes signals, not a dedicated
  ctx key, so its call signature stays unchanged), and
* persists the analyses to disk (constraint **C-1**) so the ``solidify``
  process's acceptance gate (Sprint A1) can read them across the process
  boundary.

Naming uses ``causal_*`` throughout to avoid collision with the pre-existing
``failure_diagnosis`` session-log concept (constraint **C-2**).

Gated by feature flag ``enable_diagnosis`` (off by default → the phase is a
no-op and the pipeline behaves identically to before).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolver.config import DIAGNOSIS_INTERVAL, DIAGNOSIS_MAX_EVENTS
from evolver.gep.asset_store import atomic_write_json
from evolver.gep.diagnosis.brief import (
    render_causal_brief,
    root_cause_signal_keys,
)
from evolver.gep.diagnosis.causal import CausalAnalysisError, analyze
from evolver.gep.diagnosis.schemas import CausalAnalysis
from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_gep_assets_dir

_ARTIFACT_FORMAT = "evolver.diagnosis_artifact.v0"


def _is_failed_event(event: Any) -> bool:
    """True iff *event* is a dict whose outcome is not a success."""
    if not isinstance(event, dict):
        return False
    outcome = event.get("outcome")
    if isinstance(outcome, dict):
        return str(outcome.get("status") or "").lower() != "success"
    # Missing outcome counts as not-yet-succeeded → treat as failed-ish.
    return True


def _persist_analyses(
    cycle_id: str,
    analyses: list[CausalAnalysis],
    brief: str,
) -> str:
    """Write analyses + brief to disk for cross-process reads (C-1)."""
    diag_dir = get_gep_assets_dir() / "diagnosis"
    diag_dir.mkdir(parents=True, exist_ok=True)
    safe_cycle = cycle_id or f"t{int(time.time())}"
    path = diag_dir / f"{safe_cycle}.json"
    payload = {
        "format": _ARTIFACT_FORMAT,
        "cycle_id": cycle_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "causal_brief": brief,
        "analyses": [a.model_dump() for a in analyses],
    }
    atomic_write_json(path, payload)
    return str(path)


def run_diagnosis(
    events: list[dict[str, Any]],
    *,
    max_events: int = DIAGNOSIS_MAX_EVENTS,
) -> list[CausalAnalysis]:
    """Analyze failed *events* (degraded; LLM wiring arrives in Sprint D)."""
    failed = [e for e in events if _is_failed_event(e)]
    analyses: list[CausalAnalysis] = []
    for event in failed[:max_events]:
        try:
            analyses.append(analyze(event, llm_call=None))
        except CausalAnalysisError:
            continue
    return analyses


async def diagnosis_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pipeline phase. No-op when ``enable_diagnosis`` is off (regression-safe)."""
    if not is_enabled("enable_diagnosis"):
        return ctx

    cycle_num = int(ctx.get("cycle_num", 1) or 1)
    if DIAGNOSIS_INTERVAL > 1 and (cycle_num % DIAGNOSIS_INTERVAL) != 0:
        return ctx

    events_raw = ctx.get("recent_events", [])
    events = [e for e in events_raw if isinstance(e, dict)]
    if not events:
        ctx["causal_brief"] = ""
        return ctx

    analyses = run_diagnosis(events)
    brief = render_causal_brief(analyses)
    ctx["causal_brief"] = brief
    ctx["causal_analyses"] = [a.model_dump() for a in analyses]

    # C-4: inject root_cause signal keys into ctx["signals"] (select reads signals).
    new_keys = root_cause_signal_keys(analyses)
    if new_keys:
        signals = list(ctx.get("signals", []))
        for key in new_keys:
            if key not in signals:
                signals.append(key)
        ctx["signals"] = signals
        ctx["causal_signals_merged"] = new_keys

    # C-1: persist for the solidify process's acceptance gate (Sprint A1).
    if analyses:
        ref = _persist_analyses(
            str(ctx.get("cycle_id", "")),
            analyses,
            brief,
        )
        ctx["causal_analyses_ref"] = ref

    return ctx


def load_persisted_analyses(ref: str) -> list[CausalAnalysis]:
    """Read analyses back from a persisted artifact path (used by Sprint A1)."""
    path = Path(ref)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    out: list[CausalAnalysis] = []
    for raw in payload.get("analyses") or []:
        try:
            out.append(CausalAnalysis.model_validate(raw))
        except Exception:
            continue
    return out


__all__ = [
    "diagnosis_phase",
    "load_persisted_analyses",
    "run_diagnosis",
]
