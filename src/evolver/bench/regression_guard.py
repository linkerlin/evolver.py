"""No-regression assertion — the charter's "unacceptable regressions" gate.

EvoOntology asks a Candidate to declare what must NOT get worse, then asserts
each declaration before an Accept. evolver adopts it with one addition: the
declaration can only ADD constraints, never remove the ones the machine
already owns.

Two floor sources, merged by :func:`merge_floors`:

1. **The global baseline list** — every val task must not fall below the
   Parent's own score *on that same task*. Derived from the baseline's
   ``per_task`` record, which only an Accept (or the separate Parent
   measurement) writes. A candidate cannot shrink it: it is not asked.
2. **The candidate's declaration** — the hypothesis may add floors of its
   own (``no_regressions``). These bind *in addition*, and may only cite
   train ids: the val reserve stays sealed, so a candidate cannot claim to
   know val task ids.

Why per-task at all: the aggregate gate sees only the mean. A candidate can
raise the mean while collapsing one task — the aggregate rises, the pack
silently loses a capability, and the old rule ("only a drop rejects") ships
it. The floor list is what closes that hole.

A baseline without a ``per_task`` record is NOT a waiver. An unassertable
floor is an unmeasured floor, and unmeasured rejects (演进方案.md §5.2).

Harvested from EvoOntology ``evaluation/evaluation.py``
(``unacceptable_regressions``); no Node.js equivalent. Charter 2026-09-26.
"""

from __future__ import annotations

import math
from typing import Any, Final

#: Verdict reasons (stable strings — tests and the instrument cite them).
REASON_NO_FLOOR_SOURCE: Final = "baseline_without_per_task"
REASON_NON_FINITE_FLOOR: Final = "non_finite_floor"
REASON_BAD_DECLARATION: Final = "bad_regression_declaration"
REASON_REGRESSION: Final = "regression_below_floor"
REASON_UNMEASURED_TASK: Final = "regression_check_unmeasured"

#: A declaration may only add floors for train tasks. The val reserve is
#: sealed — a candidate that cites val ids is claiming knowledge it must not
#: have, and the honest answer is a refusal, not a filtered-out entry.
DECLARATION_SPLIT: Final = "train"


def _finite(value: Any) -> bool:
    """True for a real number. ``bool`` is excluded: ``True == 1`` would
    otherwise pass as a score of one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# ---------------------------------------------------------------------------
# Floor sources
# ---------------------------------------------------------------------------


def floors_from_baseline(baseline: dict[str, Any] | None) -> dict[str, float] | None:
    """The machine's floor list: the Parent's own score on every val task.

    Returns ``None`` when the baseline carries no usable ``per_task`` record
    — that is a refusal to guess, not an empty list of things to check.
    """
    if not isinstance(baseline, dict):
        return None
    raw = baseline.get("per_task")
    if not isinstance(raw, dict) or not raw:
        return None
    floors: dict[str, float] = {}
    for key, value in raw.items():
        if not _finite(value):
            return None
        floors[str(key)] = float(value)
    return floors or None


def floors_from_declaration(
    payload: dict[str, Any] | None,
    *,
    task_ids: dict[str, list[str]] | None = None,
) -> tuple[dict[str, float], str]:
    """The candidate's own additions, or ``({}, reason)`` when unusable.

    Shape::

        {"no_regressions": [{"id": "<task id>", "floor": 0.5}, ...]}

    An absent key is a legal "I add nothing" — the global list still binds.
    A malformed one is not: a declaration that cannot be read is a
    declaration that cannot be asserted.
    """
    if not isinstance(payload, dict):
        return {}, ""
    raw = payload.get("no_regressions")
    if raw is None:
        return {}, ""
    if not isinstance(raw, list):
        return {}, REASON_BAD_DECLARATION

    allowed: set[str] | None = None
    if task_ids is not None:
        allowed = {str(x) for x in task_ids.get(DECLARATION_SPLIT) or ()}

    floors: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict):
            return {}, REASON_BAD_DECLARATION
        key = item.get("id") or item.get("task_id") or item.get("task")
        floor = item.get("floor")
        if not isinstance(key, str) or not key.strip():
            return {}, REASON_BAD_DECLARATION
        if not _finite(floor):
            return {}, REASON_BAD_DECLARATION
        if allowed is not None and key.strip() not in allowed:
            return {}, REASON_BAD_DECLARATION
        floors[key.strip()] = float(floor)
    return floors, ""


def merge_floors(
    base: dict[str, float] | None,
    declared: dict[str, float],
) -> dict[str, float]:
    """Union of both sources — a declaration may only tighten, never loosen.

    When both name a task the STRICTER (higher) floor wins: a candidate
    declaring a weaker floor than the Parent's own is asking to be allowed
    to regress, and the answer is no.
    """
    merged: dict[str, float] = dict(base or {})
    for key, value in declared.items():
        current = merged.get(key)
        merged[key] = value if current is None else max(current, value)
    return merged


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------


def violators(
    rounds: list[list[dict[str, Any]]],
    floors: dict[str, float],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Tasks that fell below their floor in ANY replicate.

    Every replicate is checked, not just the mean: reproducibility cuts both
    ways — a task can clear its floor on average while one solve collapses
    it. Returns ``(violations, unmeasured_ids)``.
    """
    violations: list[dict[str, Any]] = []
    unmeasured: list[str] = []
    for index, per_task in enumerate(rounds or [], start=1):
        if not isinstance(per_task, list):
            continue
        for entry in per_task:
            if not isinstance(entry, dict):
                continue
            tid = str(entry.get("id") or "")
            floor = floors.get(tid)
            if floor is None:
                continue
            score = entry.get("score")
            if entry.get("status") != "graded" or not _finite(score):
                unmeasured.append(tid)
                continue
            if float(score) < floor:
                violations.append(
                    {
                        "id": tid,
                        "replicate": index,
                        "score": float(score),
                        "floor": floor,
                        "delta": round(float(score) - floor, 4),
                    }
                )
    return violations, sorted(set(unmeasured))


def assert_no_regression(
    rounds: list[list[dict[str, Any]]],
    *,
    baseline: dict[str, Any] | None,
    declaration: dict[str, Any] | None = None,
    task_ids: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Assert every floor before an Accept. Returns a verdict dict.

    ``ok`` is the only thing that may precede an Accept. A missing floor
    source, a malformed declaration, a non-finite floor, an unmeasured task,
    and an actual regression all return ``ok=False`` — none of them is a
    waiver, and none of them writes a baseline.
    """
    base = floors_from_baseline(baseline)
    if base is None:
        return {
            "ok": False,
            "reason": REASON_NO_FLOOR_SOURCE,
            "floors": {},
            "violations": [],
        }

    declared, reason = floors_from_declaration(declaration, task_ids=task_ids)
    if reason:
        return {"ok": False, "reason": reason, "floors": {}, "violations": []}

    floors = merge_floors(base, declared)
    if any(not _finite(value) for value in floors.values()):
        return {
            "ok": False,
            "reason": REASON_NON_FINITE_FLOOR,
            "floors": floors,
            "violations": [],
        }

    found, unmeasured = violators(rounds, floors)
    if unmeasured:
        return {
            "ok": False,
            "reason": REASON_UNMEASURED_TASK,
            "floors": floors,
            "violations": [],
            "unmeasured_tasks": unmeasured,
        }
    if found:
        return {
            "ok": False,
            "reason": REASON_REGRESSION,
            "floors": floors,
            "violations": found,
        }
    return {
        "ok": True,
        "reason": "no_regression",
        "floors": floors,
        "violations": [],
        "declared_floors": declared,
    }


__all__ = [
    "DECLARATION_SPLIT",
    "REASON_BAD_DECLARATION",
    "REASON_NON_FINITE_FLOOR",
    "REASON_NO_FLOOR_SOURCE",
    "REASON_REGRESSION",
    "REASON_UNMEASURED_TASK",
    "assert_no_regression",
    "floors_from_baseline",
    "floors_from_declaration",
    "merge_floors",
    "violators",
]
