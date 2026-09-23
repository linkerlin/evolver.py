"""Evidence pack dispatch — failure-side evidence for the executor (RSI P1-4).

L2 boundary in arXiv:2609.11873 terms: "the system turns observed evidence
into the next experiment". The dispatch prompt already carries the SUCCESS
side (Recall Hints) and generic rejection memory (Wiki Impact headings), but
never answers the executor's most decision-relevant question: **what has this
signal family already tried, what happened, and which edits are duplicates?**

This module assembles that answer from ``events.jsonl``:

- family membership = shared signal heads (``base`` before ``:``), the same
  normalization the meta-report uses for distinctive heads;
- every family attempt (newest first) with outcome, script/landed genes,
  rejection reason, and a short fingerprint digest of the added lines —
  digests are the duplicate guard: re-running a listed fingerprint wastes a
  cycle (dogfood rounds kept re-dispatching already-landed genes);
- a scoreboard plus an explicit escape hatch: when every accepted approach
  still leaves the family failing, prefer a NEW strategy through the
  mechanical proposal channel (S29 ``swarm_propose`` / ``solidify
  --proposal``) over re-running a listed gene. Proposals pass the same
  verifier — strategy autonomy widens, acceptance authority does not.

Honesty constraints frozen by the anchor probe (case-evidence-pack-honesty):

1. family-matched failures MUST appear in the rendered pack — dropping them
   would hide the engine's own failure record from its executor (a
   self-preference loop, the RQGM warning applied to prompts);
2. the render budget is enforced with an explicit omission count, never a
   silent drop;
3. no new ``EVOLVER_*`` knobs — budgets are module constants.

No Node.js equivalent; evolver.py self-research addition (RSI P1-4).
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

#: Same-family events considered per pack (most recent wins).
EVIDENCE_PACK_MAX_EVENTS: Final = 8
#: Hard budget for the rendered prompt section.
EVIDENCE_PACK_MAX_CHARS: Final = 2400

_PROPOSAL_HINT = (
    "If accepted approaches keep leaving this family failing, prefer a NEW strategy "
    "via the mechanical proposal channel (swarm_propose / solidify --proposal) over "
    "re-running a listed gene — proposals pass the same verification gates."
)


def _heads(raw: list[Any] | tuple[Any, ...] | None) -> set[str]:
    out: set[str] = set()
    for item in raw or []:
        text = str(item).strip()
        if text:
            out.add(text.split(":", 1)[0])
    return out


def _event_heads(event: dict[str, Any]) -> set[str]:
    raw = event.get("signals") or (event.get("mutation") or {}).get("trigger_signals") or []
    return _heads(raw)


def _attempt_digest(event: dict[str, Any]) -> str:
    """Short digest of the added lines (duplicate guard).

    Prefers ``novelty_added`` (strict ``+`` payload lines recorded on
    cascade/novelty rejections), falls back to the diff snapshot on successes.
    Events without editable text carry no digest — nothing to duplicate.
    """
    blob = str(event.get("novelty_added") or event.get("diff_snapshot") or "")
    blob = blob.strip()
    if not blob:
        return ""
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()[:8]


def _landed(event: dict[str, Any]) -> list[str]:
    mut = event.get("mutation") or {}
    ids = mut.get("landed_gene_ids") or (
        [] if not mut.get("landed_gene_id") else [mut["landed_gene_id"]]
    )
    return [str(g) for g in ids if g]


def build_evidence_pack(
    events: list[dict[str, Any]],
    signals: list[str] | tuple[str, ...] | None,
    *,
    limit: int = EVIDENCE_PACK_MAX_EVENTS,
    diagnostic_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the failure-side evidence pack for the current signal family.

    Pure function over the event lineage; no I/O. Returns an empty ``attempts``
    list when the family is novel (nothing has been tried yet).

    ``diagnostic_entries`` (round-76, P2-7 read side): prior attributions from
    the diagnostic ledger — surfaced as ``prior_attribution`` when a rejected
    attempt's symptom matches a ledger entry that has a blamed component.
    """
    heads = _heads(list(signals or []))
    if not heads:
        return {
            "family_heads": sorted(heads),
            "attempts": [],
            "accepted": 0,
            "rejected": 0,
            "digests": [],
        }
    family = [e for e in events if isinstance(e, dict) and _event_heads(e) & heads][
        -max(1, limit) :
    ]

    attempts: list[dict[str, Any]] = []
    digests: list[str] = []
    accepted = rejected = 0
    for event in family:
        outcome = event.get("outcome") or {}
        status = str(outcome.get("status") or "unknown")
        if status == "success":
            accepted += 1
        elif status == "failed":
            rejected += 1
        mut = event.get("mutation") or {}
        reason = str(
            outcome.get("error") or (event.get("acceptance_result") or {}).get("reason") or ""
        )[:80]
        digest = _attempt_digest(event)
        if digest and digest not in digests:
            digests.append(digest)
        attempts.append(
            {
                "event_id": str(event.get("id") or ""),
                "status": status,
                "gene_id": str(event.get("gene_id") or mut.get("gene_id") or ""),
                "landed_gene_ids": _landed(event),
                "reason": reason,
                "digest": digest,
            }
        )
    return {
        "family_heads": sorted(heads),
        "attempts": attempts,
        "accepted": accepted,
        "rejected": rejected,
        "digests": digests,
        "prior_attribution": _prior_attribution(attempts, diagnostic_entries or []),
    }


def _prior_attribution(
    family: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> str:
    """Most recent resolved attribution matching a family failure (round-76).

    Matches the failed attempt's one-line reason against ledger symptom
    tails via trigram CONTAINMENT (the reason is a short excerpt of a
    longer tail — Jaccard would dilute, containment stays 1.0 for a true
    subset). Empty string when nothing matches.
    """
    from evolver.gep.diagnostic_ledger import containment

    for attempt in reversed(family):
        if attempt.get("status") != "failed":
            continue
        reason = str(attempt.get("reason") or "")
        if not reason:
            continue
        for m in entries:
            if not m.get("resolved"):
                continue
            tail = str(m.get("symptom_tail") or "")
            if tail and containment(reason, tail) >= 0.9:
                return f"{m.get('signature', '?')} → {m.get('blamed_component', '?')}"
    return ""


def _attempt_line(attempt: dict[str, Any]) -> str:
    landed = ",".join(attempt["landed_gene_ids"]) or "-"
    gene = attempt["gene_id"] or "-"
    line = (
        f"- [{attempt['status']}] {attempt['event_id'] or '?'} "
        f"gene={gene} landed={landed} fp={attempt['digest'] or 'n/a'}"
    )
    if attempt["reason"]:
        line += f" | {attempt['reason']}"
    return line


def render_evidence_pack(
    pack: dict[str, Any] | None,
    *,
    max_chars: int = EVIDENCE_PACK_MAX_CHARS,
) -> str:
    """Render the pack as a prompt section within a hard budget.

    Empty/absent packs render as ``""`` (novel family — nothing to say).
    When the budget forces row omissions the OLDEST attempts are dropped and
    an explicit ``(+K older family attempts omitted for budget)`` note is
    appended — evidence is never silently dropped.
    """
    if not pack or not pack.get("attempts"):
        return ""
    attempts = list(pack["attempts"])
    accepted = int(pack.get("accepted") or 0)
    rejected = int(pack.get("rejected") or 0)

    header = [
        "## Evidence Pack — prior attempts in this signal family (do NOT repeat)",
        f"Family heads: {', '.join((pack.get('family_heads') or [])[:6])}",
        f"Scoreboard: {len(attempts)} attempts | {accepted} accepted | {rejected} rejected",
    ]
    digest_line = (
        "Already-tried edit fingerprints: " + ", ".join(pack.get("digests") or [])
        if pack.get("digests")
        else ""
    )
    footer = [line for line in (digest_line, _PROPOSAL_HINT) if line]

    fixed = len("\n".join(header + footer)) + 8  # separators + omission note room
    budget = max(200, max_chars - fixed)

    rows: list[str] = []
    used = 0
    omitted = 0
    for attempt in reversed(attempts):  # newest first
        line = _attempt_line(attempt)
        if used + len(line) + 1 > budget:
            omitted = len(attempts) - len(rows)
            break
        rows.append(line)
        used += len(line) + 1
    if omitted:
        rows.append(f"... (+{omitted} older family attempts omitted for budget — see events.jsonl)")

    return "\n".join(header + rows + footer)[:max_chars]


__all__ = [
    "EVIDENCE_PACK_MAX_CHARS",
    "EVIDENCE_PACK_MAX_EVENTS",
    "build_evidence_pack",
    "render_evidence_pack",
]
