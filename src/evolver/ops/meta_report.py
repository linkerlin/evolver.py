"""Improvement-mechanism telemetry (RSI P0-2, arXiv:2609.11873 §3.6.5).

Read-only aggregation over ``events.jsonl`` + ``feedback.jsonl`` answering the
question the soak report never asks: **does the engine's improvement machinery
get better at improving?** (structural vs effective L5 — HGM's distinction
between current performance and the ability to produce better successors.)

Panels (Table-8 of the paper, adapted to available telemetry):
- adaptivity   : accepted/rejected trajectory across rolling windows
- retention    : recurrence of the trigger signals a landed gene addressed
- transfer     : landed genes re-appearing under different signal families
- efficiency   : rounds per validated gain (cost proxies where recorded)
- stability    : rollbacks (failed events) + degraded feedback counts
- meta_recursion : structural-L5 audit rows — mutations that touched the
  improvement machinery itself, with their descendants' outcomes
- library      : RSI P1-5 retrieval quality — landed-gene resolution rate,
  lifecycle status counts, zero-work candidates (retirement triggers)
- library_provenance : Harness2 (Figure 10) origin attribution — classifies
  evaluated rounds into ``direct_copy``, ``adapted``, or ``novel`` relative to
  the library snapshot and tracks success rate by origin.

Descendant quality: per landed gene, the K rounds after landing — did its
trigger signals recur (unresolved) or vanish (resolved)?
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.config import ANCHOR_TRIGGER_SURFACES
from evolver.gep.gene_lifecycle import LIFECYCLE_MIN_OBSERVATIONS, landing_stats
from evolver.gep.git_ops import normalize_rel_path

# Surfaces whose mutation means "the improvement machinery edited itself"
# (structural-L5). Verifier surfaces (anchor triggers) plus the evolution
# engine's own selector/mutation/prompt/pipeline code. Round-23: this module
# itself is in ANCHOR_TRIGGER_SURFACES — the meter is part of the machinery
# it audits (RSI audit 5.3-3).
META_MECHANISM_SURFACES: tuple[str, ...] = (
    *ANCHOR_TRIGGER_SURFACES,
    "src/evolver/gep/adaptive.py",
    "src/evolver/gep/mutation.py",
    "src/evolver/gep/prompt.py",
    "src/evolver/gep/selector.py",
    "src/evolver/evolve/",
)

_DESCENDANT_WINDOW_EVENTS = 5
_DIFF_FILE_RE = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)


def _event_ts(e: dict[str, Any]) -> str:
    return str(e.get("timestamp") or "")


def _files_touched(e: dict[str, Any]) -> list[str]:
    """Heuristic file list from the (truncated) diff snapshot headers."""
    blob = str(e.get("diff_snapshot") or "") + "\n" + str(e.get("novelty_fingerprint") or "")
    return [normalize_rel_path(m) for m in _DIFF_FILE_RE.findall(blob)]


def _landed_genes(e: dict[str, Any]) -> list[str]:
    m = e.get("mutation") or {}
    ids = m.get("landed_gene_ids") or ([] if not m.get("landed_gene_id") else [m["landed_gene_id"]])
    return [str(g) for g in ids if g]


def _trigger_signals(e: dict[str, Any]) -> set[str]:
    sig = e.get("signals") or (e.get("mutation") or {}).get("trigger_signals") or []
    return {str(s) for s in sig}


def _mechanism_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structural-L5 audit: mutations on the improvement machinery with the
    success rate of the rounds that followed them."""
    rows: list[dict[str, Any]] = []
    for idx, e in enumerate(events):
        touched = [
            f
            for f in _files_touched(e)
            if any(f == p or f.startswith(p) for p in META_MECHANISM_SURFACES)
        ]
        if not touched:
            continue
        descendants = events[idx + 1 : idx + 1 + _DESCENDANT_WINDOW_EVENTS]
        desc_outcomes = [str((d.get("outcome") or {}).get("status") or "") for d in descendants]
        rows.append(
            {
                "event_id": e.get("id"),
                "timestamp": _event_ts(e),
                "landed_genes": _landed_genes(e),
                "outcome": (e.get("outcome") or {}).get("status"),
                "mechanism_files": sorted(set(touched))[:6],
                "descendants": len(descendants),
                "descendant_success_rate": (
                    round(sum(1 for o in desc_outcomes if o == "success") / len(desc_outcomes), 3)
                    if desc_outcomes
                    else None
                ),
                "anchor_result": (e.get("anchor_result") or None),
            }
        )
    return rows


def _descendant_quality(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per landed gene: did its trigger signals recur in the following rounds?"""
    rows: list[dict[str, Any]] = []
    for idx, e in enumerate(events):
        landed = _landed_genes(e)
        if not landed or (e.get("outcome") or {}).get("status") != "success":
            continue
        triggers = _trigger_signals(e)
        descendants = events[idx + 1 : idx + 1 + _DESCENDANT_WINDOW_EVENTS]
        recurred = sum(
            1
            for d in descendants
            if triggers
            and triggers & _trigger_signals(d)
            and (d.get("outcome") or {}).get("status") == "failed"
        )
        rows.append(
            {
                "landed_gene": landed[0],
                "event_id": e.get("id"),
                "trigger_signals": sorted(triggers)[:6],
                "descendants_observed": len(descendants),
                "signal_recurrence_in_failures": recurred,
                "resolved": len(descendants) > 0 and recurred == 0,
                "unknown": len(descendants) == 0,
            }
        )
    return rows


def _improver_tool_panel(
    episodes: list[dict[str, Any]], inspect_calls: list[dict[str, Any]]
) -> dict[str, Any]:
    """Improver-tool usage (经验即证据 §5.4): how often the applied gene was an
    improver-tool gene, counted once per round.
    """
    from evolver.gep.asset_store import load_genes

    library = {str(g.get("id")): g for g in load_genes()}

    def _is_improver(gene_id: str, gene_field: Any) -> bool:
        if isinstance(gene_field, dict):
            if gene_field.get("target_hook") == "improver_tool":
                return True
            if gene_field.get("mechanism_family") == "improver_tools":
                return True
        gene = library.get(gene_id)
        if gene:
            return bool(
                gene.get("target_hook") == "improver_tool"
                or gene.get("mechanism_family") == "improver_tools"
            )
        return False

    total = len(episodes)
    improver_rounds = 0
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        raw_gene = episode.get("gene")
        gene: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
        gene_id = str(gene.get("id") or episode.get("gene_id") or "")
        if _is_improver(gene_id, gene):
            improver_rounds += 1
    inspect_sessions = {
        str(call["session_run_id"])
        for call in inspect_calls
        if isinstance(call, dict) and call.get("session_run_id")
    }
    return {
        "rounds": total,
        "improver_tool_rounds": improver_rounds,
        "usage_rate": (round(improver_rounds / total, 3) if total else None),
        "episode_inspect_calls": len(inspect_calls),
        "episode_inspect_sessions": len(inspect_sessions),
        "note": (
            "fraction of recorded rounds whose applied gene is an improver-tool "
            "gene (target_hook=improver_tool); counted once per round, recomputed "
            "from the episode record"
        ),
    }


def rere_panel(sessions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Mean RERE over accepted sessions. Missing sessions stay unmeasured.

    This panel is a report. It is not read by the frozen acceptance gate.
    """
    from evolver.experiment.metrics import rere_score

    if not sessions:
        return {
            "rere_score": None,
            "accepted_scored": 0,
            "sessions": 0,
            "note": "unmeasured",
        }
    scores: list[float] = []
    for run in sessions:
        if not isinstance(run, dict) or run.get("status") != "accepted":
            continue
        rounds = run.get("round")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            continue
        scores.append(rere_score(accepted=True, rounds_used=rounds))
    mean = round(sum(scores) / len(scores), 4) if scores else None
    return {
        "rere_score": mean,
        "accepted_scored": len(scores),
        "sessions": len(sessions),
        "note": "observational; r_ref=2; not a gate input",
    }


def _extract_added_lines_text(diff_snapshot: str) -> str:
    """Return non-header added lines from a unified diff."""
    lines: list[str] = []
    for raw in diff_snapshot.splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:].strip()
            if content:
                lines.append(content)
    return "\n".join(lines)


def _library_corpus_texts(library_entries: list[dict[str, Any]] | None) -> list[str]:
    """Extract comparable strategy/code strings from library gene entries."""
    if not library_entries:
        return []
    texts: list[str] = []
    for item in library_entries:
        if not isinstance(item, dict):
            continue
        parts: list[str] = []
        for key in ("summary", "lesson", "cue", "content", "diff_snapshot"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        for list_key in ("strategy", "validation"):
            seq = item.get(list_key)
            if isinstance(seq, list):
                parts.extend(str(x).strip() for x in seq if str(x).strip())
        joined = "\n".join(parts)
        if len(joined) >= 6:
            texts.append(joined)
    return texts


def _trigram_set(text: str) -> set[str]:
    norm = " ".join(text.lower().split())
    if len(norm) < 3:
        return {norm} if norm else set()
    return {norm[i : i + 3] for i in range(len(norm) - 2)}


def _candidate_provenance_score(candidate_text: str, ref_text: str) -> float:
    """Fraction of *candidate_text* character 3-grams present in *ref_text*."""
    cand_grams = _trigram_set(candidate_text)
    ref_grams = _trigram_set(ref_text)
    if not cand_grams or not ref_grams:
        return 0.0
    return len(cand_grams & ref_grams) / len(cand_grams)


def library_provenance_panel(
    events: list[dict[str, Any]],
    library_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Harness2 (Figure 10) Library Provenance panel: Direct Copy / Adapted / Novel.

    Classifies each event with editable text against the library corpus using
    candidate character 3-gram overlap:
    - ``direct_copy``: overlap >= 0.65
    - ``adapted``    : 0.20 <= overlap < 0.65
    - ``novel``      : overlap < 0.20
    """
    corpus = _library_corpus_texts(library_entries)
    counts = {"direct_copy": 0, "adapted": 0, "novel": 0}
    successes = {"direct_copy": 0, "adapted": 0, "novel": 0}

    for ev in events:
        if not isinstance(ev, dict):
            continue
        diff_raw = str(ev.get("diff_snapshot") or "")
        added = _extract_added_lines_text(diff_raw)
        mut = ev.get("mutation")
        mut_effect = str(mut.get("expected_effect") or "") if isinstance(mut, dict) else ""
        candidate_text = added or mut_effect
        if len(candidate_text.strip()) < 6:
            continue

        best_score = 0.0
        for ref_text in corpus:
            score = _candidate_provenance_score(candidate_text, ref_text)
            best_score = max(best_score, score)

        if best_score >= 0.65:
            origin = "direct_copy"
        elif best_score >= 0.20:
            origin = "adapted"
        else:
            origin = "novel"

        counts[origin] += 1
        is_ok = (ev.get("outcome") or {}).get("status") == "success"
        if is_ok:
            successes[origin] += 1

    evaluated = sum(counts.values())
    library_backed = counts["direct_copy"] + counts["adapted"]
    success_rate_by_origin = {
        key: (round(successes[key] / counts[key], 3) if counts[key] else None)
        for key in ("direct_copy", "adapted", "novel")
    }
    return {
        "evaluated_events": evaluated,
        "origins": counts,
        "library_backed_events": library_backed,
        "library_backed_rate": (round(library_backed / evaluated, 3) if evaluated else None),
        "success_rate_by_origin": success_rate_by_origin,
        "note": (
            "Harness2 Fig-10 provenance: direct_copy (>=0.50 trigram containment), "
            "adapted ([0.15, 0.50)), novel (<0.15)"
        ),
    }


def load_session_runs() -> list[dict[str, Any]]:
    """Best-effort load of paired-session ``run.json`` files."""
    from evolver.gep.evolution_session import session_root

    root = session_root()
    if not root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        path = child / "run.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            runs.append(payload)
    return runs


def build_meta_report(
    events: list[dict[str, Any]],
    feedback: list[dict[str, Any]] | None = None,
    lifecycle: dict[str, str] | None = None,
    episodes: list[dict[str, Any]] | None = None,
    sessions: list[dict[str, Any]] | None = None,
    inspect_calls: list[dict[str, Any]] | None = None,
    library_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate the improvement-mechanism panel. Read-only.

    *lifecycle* is a plain ``gene_id → status`` map supplied by the caller
    (``evolver.gep.gene_lifecycle.status_map``); the report itself performs
    no file reads. *episodes* is the episode-record index (经验即证据 §5.4) —
    the source for the improver-tool usage panel; absent → that panel is empty.
    """
    feedback = feedback or []
    lifecycle = lifecycle or {}
    outcomes = [str((e.get("outcome") or {}).get("status") or "") for e in events]
    accepted = [i for i, o in enumerate(outcomes) if o == "success"]
    failed = [i for i, o in enumerate(outcomes) if o == "failed"]
    degraded = [
        f
        for f in feedback
        if str(f.get("success")) == "False" or (f.get("primary_score") or 1.0) < 0.5
    ]
    gains_traj: list[int] = []
    window = max(1, len(events) // 5) if events else 1
    for start in range(0, len(events), window):
        chunk = outcomes[start : start + window]
        gains_traj.append(sum(1 for o in chunk if o == "success"))

    head_counts: dict[str, int] = {}
    event_head_sets: list[frozenset[str]] = []
    for e in events:
        heads = frozenset(s.split(":", 1)[0] for s in _trigger_signals(e))
        event_head_sets.append(heads)
        for h in heads:
            head_counts[h] = head_counts.get(h, 0) + 1
    n_events = max(1, len(events))
    common_heads = frozenset(h for h, c in head_counts.items() if c * 2 >= n_events)
    gene_event_heads: dict[str, list[frozenset[str]]] = {}
    for e, heads in zip(events, event_head_sets, strict=True):
        distinctive = heads - common_heads
        for g in _landed_genes(e):
            gene_event_heads.setdefault(g, []).append(distinctive)
    transferred = {
        g: [sorted(h) for h in hs if h][:4]
        for g, hs in gene_event_heads.items()
        if len(hs) >= 2 and len(set(hs)) >= 2
    }

    rounds_per_gain = round(len(events) / len(accepted), 2) if accepted else None
    timed_events = [e for e in events if (e.get("validation_timing") or {}).get("total_ms")]
    timed_accepted = [
        e for e in timed_events if (e.get("outcome") or {}).get("status") == "success"
    ]
    ms_per_gain = (
        round(
            sum(int(e["validation_timing"]["total_ms"]) for e in timed_events) / len(timed_accepted)
        )
        if timed_accepted
        else None
    )
    timing_coverage = {
        "timed_events": len(timed_events),
        "timed_accepted": len(timed_accepted),
        "accepted_total": len(accepted),
    }
    dq = _descendant_quality(events)
    resolved = sum(1 for r in dq if r["resolved"])
    unknown = sum(1 for r in dq if r["unknown"])
    mechanism_rows = _mechanism_rows(events)

    landing = landing_stats(events)
    evaluable = sum(int(row["observations"]) for row in landing.values())
    resolved_landings = sum(int(row["resolved"]) for row in landing.values())
    status_counts = {"active": 0, "under_review": 0, "retired": 0}
    for gid in landing:
        status = str(lifecycle.get(gid) or "active")
        if status not in status_counts:
            status = "active"
        status_counts[status] += 1
    zero_work_candidates = sorted(
        gid
        for gid, row in landing.items()
        if int(row["observations"]) >= LIFECYCLE_MIN_OBSERVATIONS and int(row["resolved"]) == 0
    )

    from evolver.gep.evidence_pack import _attempt_digest

    first_landing_index: dict[str, int] = {}
    for i, e in enumerate(events):
        for g in _landed_genes(e):
            first_landing_index.setdefault(g, i)
    seen_digests: set[str] = set()
    reused_genes: set[str] = set()
    reuse_events = 0
    novel_edits = 0
    for i, e in enumerate(events):
        gid = str(e.get("gene_id") or "")
        digest = _attempt_digest(e)
        if gid in first_landing_index and i > first_landing_index[gid]:
            reused_genes.add(gid)
            reuse_events += 1
            if digest and digest not in seen_digests:
                novel_edits += 1
        if digest:
            seen_digests.add(digest)
    faithful_use = {
        "reused_genes": len(reused_genes),
        "retrieval_rate": (round(len(reused_genes) / len(landing), 3) if landing else None),
        "reuse_events": reuse_events,
        "novel_edits": novel_edits,
        "faithful_use_rate": round(novel_edits / reuse_events, 3) if reuse_events else None,
    }

    timed_ms = sorted(int(e["validation_timing"]["total_ms"]) for e in timed_events)
    timed_failed_ms = sum(
        int(e["validation_timing"]["total_ms"])
        for e in timed_events
        if (e.get("outcome") or {}).get("status") != "success"
    )
    total_ms = sum(timed_ms)
    median_ms = timed_ms[len(timed_ms) // 2] if timed_ms else None
    mean_ms = round(total_ms / len(timed_ms)) if timed_ms else None
    cost_panel = {
        "timed_events": len(timed_ms),
        "median_ms_per_event": median_ms,
        "mean_ms_per_event": mean_ms,
        "total_engine_ms": total_ms if timed_ms else 0,
        "rejection_ms_share": round(timed_failed_ms / total_ms, 3) if total_ms else None,
        "k2_extra_ms_per_cycle": median_ms,
        "note": (
            "median is the honest central cost — the mean is inflated by "
            "pre-round-20 sleep-polluted outliers the append-only ledger "
            "cannot revise (DEBUG #31); K=2 projection prices one more "
            "candidate per cycle at the median full-validation cost"
        ),
    }

    return {
        "panel": {
            "adaptivity": {
                "events": len(events),
                "accepted": len(accepted),
                "failed": len(failed),
                "accepted_per_window": gains_traj,
            },
            "retention": {
                "landed_genes_tracked": len(dq),
                "signal_recurrence_free": resolved,
                "insufficient_descendants": unknown,
                "note": (
                    "signal_recurrence_free == library panel's resolved count "
                    "(same landing-window statistic, different framing)"
                ),
            },
            "transfer": {
                "genes_under_multiple_signal_families": len(transferred),
                "detail": transferred,
            },
            "efficiency": {
                "rounds_per_validated_gain": rounds_per_gain,
                "validation_ms_per_validated_gain": ms_per_gain,
                "timed_events": len(timed_events),
                "timing_coverage": timing_coverage,
                "note": (
                    "time-based over the timed population "
                    f"({len(timed_accepted)}/{len(accepted)} accepted timed); "
                    "else count-based"
                    if ms_per_gain is not None
                    else "count-based until validation_timing lands on events"
                ),
            },
            "stability": {
                "failed_events": len(failed),
                "degraded_feedback": len(degraded),
            },
            "meta_recursion": {
                "structural_l5_mutations": len(mechanism_rows),
            },
            "library": {
                "landed_genes": len(landing),
                "landings_tracked": sum(int(row["landings"]) for row in landing.values()),
                "evaluable_landings": evaluable,
                "resolution_rate": (round(resolved_landings / evaluable, 3) if evaluable else None),
                "zero_work_candidates": zero_work_candidates,
                "lifecycle": status_counts,
                "faithful_use": faithful_use,
            },
            "library_provenance": library_provenance_panel(events, library_entries),
            "improver_tools": _improver_tool_panel(episodes or [], inspect_calls or []),
            "cost": cost_panel,
            "rere": rere_panel(sessions),
        },
        "mechanism_audit": mechanism_rows,
        "descendant_quality": dq,
    }


def load_feedback_events(evolution_dir: Path | None = None) -> list[dict[str, Any]]:
    """Best-effort load of feedback.jsonl (missing file → empty)."""
    from evolver.gep.paths import get_evolution_dir

    path = (evolution_dir or get_evolution_dir()) / "feedback.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


__all__ = [
    "META_MECHANISM_SURFACES",
    "build_meta_report",
    "library_provenance_panel",
    "load_feedback_events",
    "load_session_runs",
    "rere_panel",
]
