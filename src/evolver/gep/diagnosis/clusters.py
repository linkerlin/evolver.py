"""Cross-case causal clustering.

Methodology inspired by Self-Harness (arXiv:2606.09498, ``integrated.py``
``build_verifier_causal_clusters``). No Node.js equivalent; evolver.py
self-research addition (Sprint B2).

Clusters failed-case :class:`CausalAnalysis` objects by their root-cause
``(terminal_cause, criticality, agent_mechanism)`` signature, sorts clusters by
criticality rank (``root_cause`` first), and renders a proposer-facing brief.
The brief carries Self-Harness's guidance principles: passing cases are
regression tests; select one high-confidence terminal-cause cluster; a large
terminal bucket is not actionable by itself; prefer no-op when no safe
reusable change follows.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from evolver.gep.diagnosis.causal import pick_root_cause
from evolver.gep.diagnosis.schemas import (
    CRITICALITY_RANK,
    CausalAnalysis,
    Criticality,
)

_GUIDANCE_BY_CRITICALITY: dict[str, str] = {
    "root_cause": ("high-confidence actionable — select this cluster for the next proposal"),
    "contributor": "contributing factor — treat as secondary, not primary",
    "non_terminal_friction": "non-terminal friction — informational only",
    "recovered_friction": "recovered friction — NOT actionable by itself",
    "unknown": "low confidence — treat cautiously",
}

_BRIEF_HEADER = (
    "Passing cases are regression tests — do not break them. "
    "Select ONE high-confidence terminal-cause cluster. "
    "Do not treat a large terminal bucket as actionable by itself. "
    "If no safe, reusable change follows from the evidence, prefer no-op "
    "(decline)."
)


class CausalSignature(BaseModel):
    """The (terminal_cause, criticality, agent_mechanism) clustering key."""

    model_config = ConfigDict(extra="forbid")
    terminal_cause: str
    criticality: Criticality
    agent_mechanism: str


class CausalCluster(BaseModel):
    """Failed cases sharing one root-cause signature."""

    model_config = ConfigDict(extra="forbid")
    signature: CausalSignature
    case_ids: list[str] = Field(default_factory=list)
    size: int = 0
    guidance: str = ""


def signature_of(analysis: CausalAnalysis) -> CausalSignature | None:
    """Root-cause signature of *analysis*, or ``None`` when unattributed."""
    rc = pick_root_cause(analysis)
    if rc is None:
        return None
    criticality, terminal_cause, agent_mechanism = rc
    return CausalSignature(
        terminal_cause=terminal_cause,
        criticality=criticality,
        agent_mechanism=agent_mechanism,
    )


def cluster_guidance(signature: CausalSignature) -> str:
    """Per-criticality action guidance for a cluster."""
    return _GUIDANCE_BY_CRITICALITY.get(signature.criticality, "unknown")


def build_causal_clusters(analyses: list[CausalAnalysis]) -> list[CausalCluster]:
    """Group *analyses* by root-cause signature, sorted by criticality rank.

    Sorting: ``criticality`` rank ascending (``root_cause`` first), then
    cluster ``size`` descending. Analyses without an attributed root cause are
    skipped (they carry no actionable signature).
    """
    by_key: dict[tuple[str, str, str], list[str]] = {}
    for analysis in analyses:
        sig = signature_of(analysis)
        if sig is None:
            continue
        key = (sig.terminal_cause, sig.criticality, sig.agent_mechanism)
        by_key.setdefault(key, []).append(analysis.event_id)

    clusters: list[CausalCluster] = []
    for (terminal_cause, criticality, agent_mechanism), case_ids in by_key.items():
        signature = CausalSignature(
            terminal_cause=terminal_cause,
            criticality=criticality,  # type: ignore[arg-type]
            agent_mechanism=agent_mechanism,
        )
        clusters.append(
            CausalCluster(
                signature=signature,
                case_ids=case_ids,
                size=len(case_ids),
                guidance=cluster_guidance(signature),
            )
        )

    clusters.sort(key=lambda c: (CRITICALITY_RANK.get(c.signature.criticality, 4), -c.size))
    return clusters


def render_cluster_brief(clusters: list[CausalCluster]) -> str:
    """Render a markdown brief of *clusters* for the GEP prompt.

    Returns ``""`` when *clusters* is empty (caller treats absence as "no
    clusters this cycle").
    """
    if not clusters:
        return ""
    lines: list[str] = [
        "# Causal Failure Clusters",
        "",
        _BRIEF_HEADER,
        "",
    ]
    for cluster in clusters:
        sig = cluster.signature
        lines.append(
            f"## [{sig.criticality}] {sig.terminal_cause} "
            f"(mech={sig.agent_mechanism}, cases={cluster.size})"
        )
        lines.append(f"- cases: {', '.join(cluster.case_ids)}")
        lines.append(f"- guidance: {cluster.guidance}")
    return "\n".join(lines)


__all__ = [
    "CausalCluster",
    "CausalSignature",
    "build_causal_clusters",
    "cluster_guidance",
    "render_cluster_brief",
    "signature_of",
]
