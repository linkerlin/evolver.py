"""Unified evaluation feedback — concept harvest from EvoX (Java).

EvoX's Evolving Layer paradigm is ``Target(t+1) = O(Target(t), E)`` with a
unified evaluation signal ``E`` whose contract separates three concerns:
``primaryScore`` (convergence / gate decisions), ``metrics`` (multi-dim
diagnostics) and ``textualGradient`` (natural-language direction for the next
mutation). Behavioral re-implementation of that contract only
(io.leavesfly.evox.optimizers.base.EvaluationFeedback); no code copied —
EvoX's own evaluators are largely placeholder implementations anyway.

In evolver this closes the semantic gap of the MCP swarm loop (v1.98.0):
after the host agent executes a dispatch prompt, code-level gates (solidify)
capture mechanical validity, but the semantic outcome — did the mutation
actually help? — had no channel back into selection. ``record_feedback``
journals every report (``feedback.jsonl``) and injects pending signal keys so
the next cycle's selector and dispatch prompt see it: degraded reports feed
the repair-bias channel exactly like autopoiesis friction signals.
"""

from __future__ import annotations

import datetime
import json
import secrets
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

FEEDBACK_SIGNAL_OK: Final = "swarm_feedback:ok"
FEEDBACK_SIGNAL_DEGRADED: Final = "swarm_feedback:degraded"
GRADIENT_SIGNAL_PREFIX: Final = "swarm_feedback:gradient:"
# Keep gradient signal strings prompt-sized; the full text lives in the journal.
GRADIENT_SIGNAL_MAX_CHARS: Final = 120


class EvaluationFeedback(BaseModel):
    """统一评估信号 E (EvoX 契约移植).

    三分离: ``primary_score`` 管降级判定与选择; ``metrics`` 为多维诊断;
    ``textual_gradient`` 为自然语言方向信号 (何者有效、何者无效——下轮
    变异与 TextGrad 类提示词改写的输入).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["EvaluationFeedback"] = "EvaluationFeedback"
    id: str | None = None
    agent_name: str = "host-agent"
    run_id: str | None = None
    cycle_id: str | None = None
    primary_score: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, float] = Field(default_factory=dict)
    textual_gradient: str = ""
    eval_mode: Literal["train", "validation", "test"] = "validation"
    sample_count: int = Field(default=0, ge=0)
    success: bool = True
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""

    def is_degraded(self) -> bool:
        """Below-threshold or failed reports steer the next cycle to repair."""
        from evolver.config import SWARM_FEEDBACK_DEGRADED_THRESHOLD

        return (not self.success) or self.primary_score < SWARM_FEEDBACK_DEGRADED_THRESHOLD

    def signal_keys(self) -> list[str]:
        """Pending-signal keys for the next cycle (selector + prompt visible)."""
        keys = [FEEDBACK_SIGNAL_DEGRADED if self.is_degraded() else FEEDBACK_SIGNAL_OK]
        gradient = self.textual_gradient.strip()
        if self.is_degraded() and gradient:
            keys.append(f"{GRADIENT_SIGNAL_PREFIX} {gradient[:GRADIENT_SIGNAL_MAX_CHARS]}")
        return keys


def feedback_journal_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "feedback.jsonl"


def record_feedback(fb: EvaluationFeedback) -> dict[str, Any]:
    """Fill id/timestamp, journal the report, inject next-cycle signal keys."""
    from evolver.gep.asset_store import append_pending_signals

    if not fb.id:
        fb.id = f"fb_{secrets.token_hex(6)}"
    if not fb.timestamp:
        fb.timestamp = datetime.datetime.now(datetime.UTC).isoformat()

    path = feedback_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(fb.model_dump_json() + "\n")

    injected = fb.signal_keys()
    append_pending_signals(injected)
    return {
        "ok": True,
        "feedback_id": fb.id,
        "degraded": fb.is_degraded(),
        "injected_signals": injected,
        "journal_path": str(path),
        "next_action": "swarm_tick",
    }


def load_recent_feedback(limit: int = 20) -> list[dict[str, Any]]:
    """Read the newest journal entries (oldest→newest order preserved)."""
    path = feedback_journal_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-max(1, limit) :]


__all__ = [
    "FEEDBACK_SIGNAL_DEGRADED",
    "FEEDBACK_SIGNAL_OK",
    "GRADIENT_SIGNAL_MAX_CHARS",
    "GRADIENT_SIGNAL_PREFIX",
    "EvaluationFeedback",
    "feedback_journal_path",
    "load_recent_feedback",
    "record_feedback",
]
