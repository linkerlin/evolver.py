"""Fitness ledger: r_best state for strict-improvement gating (S26.3).

No Node.js equivalent; evolver.py addition.

Mirrors the wikiskill gate state (R_val > R_best, strictly greater): a
mutation is only an improvement if its measured fitness beats the best seen
so far — **within the same measurement domain**. Domains keep incomparable
scales apart: a cascade 1.0 (stage progress) must never lock out a bench 0.83
(task pass rate), so ``solidify:*`` measurements route to the ``cascade``
domain while ``bench:health`` / ``bench:pack:<split>`` keep their own.

Domain routing from *source*:
- ``solidify:<run_id>``            → ``cascade``
- ``bench:health``                 → ``bench:health``
- ``bench:pack:<split>``           → ``bench:pack:<split>``
- anything else                    → ``misc`` (explicit, never silently mixed)

Shadow period: solidify records the verdict on the event but does not roll
back. Enforcement is gated by EVOLVER_FITNESS_GATE_ENFORCE.

Legacy state (pre-domains, top-level baseline/r_best/history) migrates to
the ``cascade`` domain on first load — it was cascade-only by construction.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolution_dir

FITNESS_STATE_FILENAME = "evolution_fitness_state.json"
CASCADE_DOMAIN = "cascade"


def fitness_state_path() -> Path:
    return get_evolution_dir() / FITNESS_STATE_FILENAME


def _empty_domain() -> dict[str, Any]:
    return {"baseline": None, "r_best": None, "history": []}


def _domain_of(source: str) -> str:
    if source.startswith("solidify:"):
        return CASCADE_DOMAIN
    if source.startswith("bench:"):
        return source
    return "misc"


def load_fitness_state() -> dict[str, Any]:
    """Return the domain-keyed ledger ``{"domains": {...}}`` (migrating the
    legacy top-level shape on first read). Corrupt files degrade to empty."""
    path = fitness_state_path()
    if not path.exists():
        return {"domains": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("domains"), dict):
            for domain in state["domains"]:
                state["domains"][domain].setdefault("baseline", None)
                state["domains"][domain].setdefault("r_best", None)
                state["domains"][domain].setdefault("history", [])
            return state
        if isinstance(state, dict) and ("r_best" in state or "baseline" in state):
            # legacy cascade-only shape → migrate
            migrated = _empty_domain()
            migrated["baseline"] = state.get("baseline")
            migrated["r_best"] = state.get("r_best")
            migrated["history"] = state.get("history") or []
            return {"domains": {CASCADE_DOMAIN: migrated}}
    except (OSError, json.JSONDecodeError):
        pass
    return {"domains": {}}


def load_domain(source_or_domain: str) -> dict[str, Any]:
    """Load one domain's ledger (empty when never measured)."""
    state = load_fitness_state()
    domain = (
        source_or_domain if source_or_domain in state["domains"] else _domain_of(source_or_domain)
    )
    return state["domains"].get(domain) or _empty_domain()


def save_fitness_state(state: dict[str, Any]) -> None:
    path = fitness_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_measurement(score: float | None, *, source: str) -> dict[str, Any] | None:
    """Record one measured score into its SOURCE'S DOMAIN. Returns the domain
    verdict entry, or None when the score is unmeasured (None) — unvalidated
    work claims nothing and must not move r_best.

    First measurement in a domain establishes its baseline (accepted, like
    the wikiskill gate's establishing run). Strictly-greater scores update
    that domain's r_best; anything else is a ``no_improvement`` verdict.
    """
    if score is None:
        return None
    domain_name = _domain_of(source)
    state = load_fitness_state()
    domain = state["domains"].get(domain_name) or _empty_domain()
    r_best = domain["r_best"]
    accepted = r_best is None or score > r_best
    if accepted:
        if r_best is None:
            domain["baseline"] = score
        domain["r_best"] = score
    verdict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "domain": domain_name,
        "source": source,
        "score": score,
        "r_best": domain["r_best"],
        "verdict": (
            "baseline_established"
            if r_best is None
            else ("improved" if accepted else "no_improvement")
        ),
    }
    domain["history"].append(verdict)
    state["domains"][domain_name] = domain
    save_fitness_state(state)
    return verdict


__all__ = [
    "CASCADE_DOMAIN",
    "FITNESS_STATE_FILENAME",
    "fitness_state_path",
    "load_domain",
    "load_fitness_state",
    "record_measurement",
    "save_fitness_state",
]
