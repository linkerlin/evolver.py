"""Sealed validation split — the val tasks must never reach design context.

Charter: 演进方案.md §5.2. The diagnosis pool (``train``) is what the executor
may reason about; the Validation Reserve (``val``) is Parent-vs-Candidate
comparison only. Neither its wording nor its expected answers may appear in
the dispatch prompt, the Evidence Pack, or the proposal round — otherwise a
candidate can win by memorizing the exam instead of getting better.

What counts as a secret:

- the val task's ``title`` and ``prompt`` (the question itself);
- its ``grader.expected`` (the answer);
- sandbox file bodies that only val tasks carry.

Two honest limits, stated rather than hidden:

1. **Shared material is not secret.** Several families reuse one fixture (the
   extract log appears in a train task too). A string that also occurs in any
   train task is public by construction and is dropped from the secrets list.
2. **Very short answers are weak evidence.** An expected value under
   ``MIN_SECRET_LEN`` characters (``"3"``, ``"cain"``) collides with ordinary
   prose, so it is not used for the verdict. It is still reported as a
   low-signal string so the omission is visible instead of silent.

The pack itself lives anchor-side and is read-only in-cycle.

No Node.js equivalent; evolver.py addition (paired-session charter).
"""

from __future__ import annotations

import json
from typing import Any

#: Expected answers shorter than this are reported but never decide a breach.
MIN_SECRET_LEN: int = 6

#: Where the seal applies. Listed so inspectors see the full surface.
SEAL_TARGETS: tuple[str, ...] = ("dispatch", "evidence_pack", "proposal_round")


class ValSealBreachError(RuntimeError):
    """A val task's wording or answer leaked into a design surface."""


def _pack_tasks() -> list[dict[str, Any]]:
    """Tasks from the frozen pack; empty when the gate is unarmed."""
    from evolver.bench.frozen_gate import load_frozen_pack

    loaded = load_frozen_pack()
    return loaded[0] if loaded else []


def task_ids() -> dict[str, list[str]]:
    """``{"train": [...], "val": [...]}`` for the frozen pack.

    Empty lists when unarmed — callers must treat "no ids" as "no claim",
    never as "everything is allowed".
    """
    buckets: dict[str, list[str]] = {"train": [], "val": []}
    for task in _pack_tasks():
        split = str(task.get("split") or "")
        task_id = str(task.get("id") or "")
        if split in buckets and task_id:
            buckets[split].append(task_id)
    return buckets


def _stringify(value: Any) -> str:
    """Normalize any expected value to a stable string."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _task_strings(task: dict[str, Any]) -> set[str]:
    """Every string that identifies this task."""
    found: set[str] = set()
    for key in ("title", "prompt"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            found.add(value.strip())
    grader = task.get("grader")
    if isinstance(grader, dict) and "expected" in grader:
        # ``grader.path`` is deliberately NOT a secret: it is a generic field
        # name ("result"), not an answer, and jailing it would fire on ordinary
        # JSON prose. Only the expected value is guarded.
        found.add(_stringify(grader["expected"]))
    sandbox = task.get("sandbox")
    if isinstance(sandbox, dict):
        for body in sandbox.values():
            if isinstance(body, str) and body.strip():
                found.add(body.strip())
    return found


def sealed_secrets() -> list[dict[str, Any]]:
    """Val-only identifying strings, longest first.

    Each entry carries ``source`` (the val task id) and ``signal``
    (``"strong"`` when it may decide a breach, ``"weak"`` when it is too
    short to trust).
    """
    tasks = _pack_tasks()
    trains = [t for t in tasks if str(t.get("split")) == "train"]
    vals = [t for t in tasks if str(t.get("split")) == "val"]
    if not vals:
        return []

    public: set[str] = set()
    for task in trains:
        public |= _task_strings(task)

    secrets: list[dict[str, Any]] = []
    for task in vals:
        tid = str(task.get("id") or "")
        for text in _task_strings(task) - public:
            secrets.append(
                {
                    "value": text,
                    "source": tid,
                    "signal": "weak" if len(text) < MIN_SECRET_LEN else "strong",
                }
            )
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for entry in sorted(secrets, key=lambda item: len(str(item["value"])), reverse=True):
        value = str(entry["value"])
        if value in seen:
            continue
        seen.add(value)
        unique.append(entry)
    return unique


def scan(text: str | None) -> list[dict[str, Any]]:
    """Secrets occurring in *text*. Strong hits decide; weak hits inform."""
    if not text:
        return []
    return [entry for entry in sealed_secrets() if str(entry["value"]) in text]


def strong_scan(text: str | None) -> list[dict[str, Any]]:
    """Secrets strong enough to reject on."""
    return [entry for entry in scan(text) if entry.get("signal") == "strong"]


def assert_sealed(text: str | None, *, where: str) -> None:
    """Raise :class:`ValSealBreachError` when strong secrets appear in *text*."""
    hits = strong_scan(text)
    if not hits:
        return
    preview = "; ".join(f"{entry['source']}: {str(entry['value'])[:60]!r}" for entry in hits[:3])
    raise ValSealBreachError(
        f"val seal breached in {where}: {len(hits)} sealed string(s) present — {preview}"
    )


#: Placeholder substituted for a sealed string in executor-facing context.
REDACTION_PLACEHOLDER: str = "[sealed:val]"


def redact(text: str | None, *, where: str) -> tuple[str, dict[str, Any]]:
    """Strip strong secrets out of executor-facing context.

    Used where the text is assembled from history (Evidence Pack, dispatch)
    and rejecting outright would break the prompt contract: the line is
    replaced with :data:`REDACTION_PLACEHOLDER` and the count is reported, so
    the omission is visible rather than silent — the same honesty rule the
    Evidence Pack already applies to its budget.
    """
    if not text:
        report = seal_report(text, where=where)
        report["redacted"] = 0
        return text or "", report

    scrubbed = text
    hits = strong_scan(scrubbed)
    for entry in hits:
        scrubbed = scrubbed.replace(str(entry["value"]), REDACTION_PLACEHOLDER)
    report = seal_report(scrubbed, where=where)
    report["redacted"] = len(hits)
    return scrubbed, report


def seal_report(text: str | None, *, where: str) -> dict[str, Any]:
    """Non-raising report for diagnostics and audit lines."""
    hits = scan(text)
    return {
        "where": where,
        "armed": bool(task_ids()["val"]),
        "hits": len(hits),
        "strong_hits": sum(1 for entry in hits if entry.get("signal") == "strong"),
        "sources": sorted({str(entry["source"]) for entry in hits}),
    }


__all__ = [
    "MIN_SECRET_LEN",
    "REDACTION_PLACEHOLDER",
    "SEAL_TARGETS",
    "ValSealBreachError",
    "assert_sealed",
    "redact",
    "scan",
    "seal_report",
    "sealed_secrets",
    "strong_scan",
    "task_ids",
]
