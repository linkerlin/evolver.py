"""Causal brief rendering + select-signal derivation.

Methodology inspired by Self-Harness (arXiv:2606.09498, ``integrated.py``
``write_verifier_causal_brief``). No Node.js equivalent; evolver.py
self-research addition (Sprint B1).

Renders a markdown brief from one or more :class:`CausalAnalysis` objects for
the GEP prompt, and derives the ``causal:root_cause:<terminal_cause>`` signal
keys that :mod:`evolver.evolve.pipeline.diagnosis` injects into
``ctx["signals"]`` (integration constraint C-4: select consumes signals, not
a dedicated ctx key, so its signature stays unchanged).
"""

from __future__ import annotations

from evolver.gep.diagnosis.causal import pick_root_cause
from evolver.gep.diagnosis.schemas import CausalAnalysis


def render_causal_brief(analyses: list[CausalAnalysis]) -> str:
    """Render a compact markdown brief for the GEP prompt.

    Returns ``""`` when *analyses* is empty (caller treats absence as "no
    diagnosis this cycle"). Root-cause stages are surfaced first; the full
    per-stage attribution follows for context.
    """
    if not analyses:
        return ""
    lines: list[str] = ["# Causal Diagnosis (terminal-cause-first)"]
    for analysis in analyses:
        rc = pick_root_cause(analysis)
        lines.append(f"## event {analysis.event_id} — {analysis.terminal_failure_kind}")
        if rc:
            criticality, terminal_cause, agent_mechanism = rc
            lines.append(
                f"- root_cause: criticality={criticality} "
                f"terminal_cause={terminal_cause} "
                f"agent_mechanism={agent_mechanism}"
            )
        else:
            lines.append("- root_cause: (unattributed — degraded or unknown)")
        for stage in analysis.stages:
            cause = stage.terminal_cause or "unknown"
            mech = stage.agent_mechanism or "unknown"
            lines.append(
                f"  - stage {stage.stage_index} [{stage.criticality}]: cause={cause} mech={mech}"
            )
    return "\n".join(lines)


def root_cause_signal_keys(analyses: list[CausalAnalysis]) -> list[str]:
    """Derive ``causal:root_cause:<terminal_cause>`` keys for select (C-4).

    One key per distinct root-cause ``terminal_cause``. Empty when no analysis
    has an attributed root cause.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for analysis in analyses:
        rc = pick_root_cause(analysis)
        if not rc:
            continue
        key = f"causal:root_cause:{rc[1]}"
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


__all__ = [
    "render_causal_brief",
    "root_cause_signal_keys",
]
