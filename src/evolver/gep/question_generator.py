"""Question generator — proactively create bounty questions for the Hub.

Equivalent to Node's ``evolver/src/gep/questionGenerator.js``.

Analyses the current signal landscape and capability gaps, then
generates structured bounty questions that can be posted to the
Hub's open-task marketplace.

Constraints
-----------
* Daily rate limit: max 3 questions.
* CRITICAL signals bypass the rate limit.
* Infrastructure errors (network, disk) are never turned into bounty questions.

Output format
-------------
Each question includes: background, reproduction steps, expected
outcome, and suggested bounty amount.

Design notes
------------
* Works entirely offline on local state.
* Uses simple heuristics — no LLM calls by default.
* Respects ``enable_question_generator`` feature flag.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_graph import try_read_memory_graph_events
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Limits
DAILY_LIMIT = 3
CRITICAL_BYPASS = True  # CRITICAL signals bypass rate limit
MIN_BOUNTY = 1.0
MAX_BOUNTY = 100.0

# State file
QUESTION_STATE_PATH = Path("evolver") / ".config" / "question_generator.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BountyQuestion:
    title: str
    background: str
    reproduction: str
    expected: str
    bounty: float
    signal_key: str
    priority: str  # low|medium|high|critical
    test_case_draft: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "background": self.background,
            "reproduction": self.reproduction,
            "expected": self.expected,
            "bounty": self.bounty,
            "signal_key": self.signal_key,
            "priority": self.priority,
            "test_case_draft": self.test_case_draft,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _load_state(path: Path | None = None) -> dict[str, Any]:
    p = path or (get_workspace_root() / QUESTION_STATE_PATH)
    if not p.exists():
        return {"daily_count": 0, "last_reset": 0, "questions": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("daily_count", 0)
        data.setdefault("last_reset", 0)
        data.setdefault("questions", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"daily_count": 0, "last_reset": 0, "questions": []}


def _save_state(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or (get_workspace_root() / QUESTION_STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)


def _reset_daily_counter(state: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    last_reset = state.get("last_reset", 0)
    if now - last_reset >= 86400:
        state["daily_count"] = 0
        state["last_reset"] = now
    return state


# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------


def _is_infrastructure_error(event: dict[str, Any]) -> bool:
    """Return True if the event looks like an infra error (network/disk)."""
    error = str(event.get("error", "")).lower()
    infra_patterns = [
        "connection",
        "timeout",
        "network",
        "econnrefused",
        "enospc",
        "disk full",
        "permission denied",
        "eacces",
    ]
    return any(p in error for p in infra_patterns)


def _signal_priority(event: dict[str, Any]) -> str:
    """Derive priority from event metadata."""
    tags = [str(t).lower() for t in event.get("tags", [])]
    if "critical" in tags or event.get("severity") == "critical":
        return "critical"
    if "high" in tags or event.get("severity") == "high":
        return "high"
    if "medium" in tags or event.get("severity") == "medium":
        return "medium"
    return "low"


def _compute_bounty(priority: str, failure_count: int) -> float:
    """Compute suggested bounty amount."""
    base: dict[str, float] = {"critical": 50.0, "high": 25.0, "medium": 10.0, "low": 5.0}
    amount = base.get(priority, 5.0)
    # Increase for repeated failures
    amount *= min(3.0, 1.0 + (failure_count - 1) * 0.3)
    return max(MIN_BOUNTY, min(MAX_BOUNTY, round(amount, 2)))


# ---------------------------------------------------------------------------
# Question drafting
# ---------------------------------------------------------------------------


def _draft_question(signal_key: str, events: list[dict[str, Any]]) -> BountyQuestion | None:
    """Draft a bounty question from a cluster of failure events."""
    # Find the most recent event as representative
    representative = None
    for ev in reversed(events):
        key = ev.get("signal_key", "")
        if not key:
            signals = ev.get("signals_snapshot") or ev.get("signals", [])
            key = " | ".join(signals[:3]) if signals else "unknown"
        if key == signal_key:
            representative = ev
            break

    if not representative:
        return None

    priority = _signal_priority(representative)
    signals = representative.get("signals_snapshot") or representative.get("signals", [])
    signal_text = " | ".join(signals[:3]) if signals else "unknown"
    outcome = representative.get("outcome", "")
    error = representative.get("error", "")

    # Count failures for this signal
    failure_count = sum(
        1
        for ev in events
        if (ev.get("signals_snapshot") or ev.get("signals", [])) == signals
        and "success" not in str(ev.get("outcome", "")).lower()
    )

    title = f"[Auto] {signal_text[:60]}"
    background = (
        f"The evolver agent repeatedly encounters failures related to "
        f"'{signal_text}'. This has occurred {failure_count} time(s) recently."
    )
    reproduction = (
        f"1. Trigger signal: {signal_text}\n"
        f"2. Observe outcome: {outcome}\n"
        f"3. Error: {error or '(none captured)'}"
    )
    expected = f"The agent should successfully handle '{signal_text}' without errors."
    bounty = _compute_bounty(priority, failure_count)

    # Draft a simple test case
    test_draft = (
        f"# Test for {signal_text}\n"
        f"def test_{signal_text.replace(' ', '_').replace('-', '_')[:30]}():\n"
        f"    # TODO: reproduce the failure condition\n"
        f"    pass\n"
    )

    return BountyQuestion(
        title=title,
        background=background,
        reproduction=reproduction,
        expected=expected,
        bounty=bounty,
        signal_key=signal_key,
        priority=priority,
        test_case_draft=test_draft,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_questions(
    *,
    events: list[dict[str, Any]] | None = None,
    max_questions: int = DAILY_LIMIT,
    state_path: Path | None = None,
) -> list[BountyQuestion]:
    """Generate bounty questions from recent failure events.

    Returns the list of newly generated questions.
    """
    if not is_enabled("enable_question_generator"):
        return []

    if events is None:
        events = try_read_memory_graph_events()

    state = _load_state(state_path)
    state = _reset_daily_counter(state)

    # Rate limit check
    if state["daily_count"] >= max_questions:
        logger.info("[QuestionGenerator] Daily limit reached (%d)", max_questions)
        return []

    # Cluster events by signal key
    signal_events: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if ev.get("type") != "attempt":
            continue
        outcome = str(ev.get("outcome", "")).lower()
        if "success" in outcome or "pass" in outcome:
            continue
        if _is_infrastructure_error(ev):
            continue

        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        key = " | ".join(signals[:3]) if signals else "unknown"
        signal_events.setdefault(key, []).append(ev)

    generated: list[BountyQuestion] = []
    for key, cluster in signal_events.items():
        if len(cluster) < 2:
            continue
        # Check if already generated
        existing = [q for q in state.get("questions", []) if q.get("signal_key") == key]
        if existing:
            continue

        priority = _signal_priority(cluster[-1])
        # CRITICAL signals bypass daily limit
        if state["daily_count"] >= max_questions and not (CRITICAL_BYPASS and priority == "critical"):
            break

        question = _draft_question(key, cluster)
        if question is None:
            continue

        generated.append(question)
        state["questions"].append(question.to_dict())
        state["daily_count"] += 1
        logger.info(
            "[QuestionGenerator] Generated question for '%s' (bounty=%.2f, priority=%s)",
            key,
            question.bounty,
            priority,
        )

        if state["daily_count"] >= max_questions:
            break

    if generated:
        _save_state(state, state_path)
    return generated


def submit_question(
    question: BountyQuestion,
    *,
    hub_client: Any | None = None,
) -> dict[str, Any] | None:
    """Submit a question to the Hub bounty system.

    Returns the Hub response, or ``None`` on failure.
    """
    try:
        from evolver.atp.hub_client import post_bounty
        import asyncio
        payload = {
            "title": question.title,
            "description": question.background,
            "reproduction": question.reproduction,
            "expected": question.expected,
            "bounty": question.bounty,
            "priority": question.priority,
            "test_case_draft": question.test_case_draft,
        }
        try:
            result = asyncio.run(post_bounty(payload))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(post_bounty(payload))
        logger.info("[QuestionGenerator] Submitted bounty '%s'", question.title)
        return result
    except Exception as exc:
        logger.warning("[QuestionGenerator] Failed to submit bounty: %s", exc)
        return None
