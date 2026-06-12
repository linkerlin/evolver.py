"""Local memory graph store and query engine.

Equivalent to evolver/src/gep/memoryGraph.js (obfuscated).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, cast

from evolver.gep.paths import get_evolution_dir, get_memory_graph_path


def _graph_path() -> Path:
    env = os.environ.get("MEMORY_GRAPH_PATH")
    if env:
        return Path(env)
    return get_memory_graph_path()


def _state_path() -> Path:
    env = os.environ.get("MEMORY_GRAPH_STATE_PATH")
    if env:
        return Path(env)
    return get_evolution_dir() / "memory_graph_state.json"


def compute_signal_key(signals: list[str] | None) -> str:
    """Deterministic key for a set of signals, order-independent."""
    if not isinstance(signals, list):
        signals = []
    cleaned = sorted({str(s).strip().lower() for s in signals if s is not None})
    canonical = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def try_read_memory_graph_events(limit: int = 10_000) -> list[dict[str, Any]]:
    path = _graph_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(cast(dict[str, Any], json.loads(line)))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    break
    except OSError:
        return []
    return events


def _append_event(event: dict[str, Any]) -> dict[str, Any]:
    path = _graph_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def _new_id(prefix: str = "mge") -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{secrets.token_hex(4)}"


def record_signal_snapshot(
    *,
    signals: list[str],
    observations: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "signal",
        "id": _new_id("sig"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "observations": observations or {},
    }
    if run_id:
        event["run_id"] = run_id
    return _append_event(event)


def record_hypothesis(
    *,
    signals: list[str],
    selected_gene: dict[str, Any] | None,
    drift_enabled: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "hypothesis",
        "id": _new_id("hyp"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "gene": selected_gene,
        "drift_enabled": drift_enabled,
    }
    if run_id:
        event["run_id"] = run_id
    saved = _append_event(event)
    signal = cast(dict[str, Any], saved.get("signal", {}))
    return {"hypothesisId": saved["id"], "signalKey": signal["key"]}


def record_attempt(
    *,
    signals: list[str],
    selected_gene: dict[str, Any] | None,
    drift_enabled: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    action_id = _new_id("act")
    event = {
        "type": "MemoryGraphEvent",
        "kind": "attempt",
        "id": _new_id("att"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "gene": selected_gene,
        "action": {"id": action_id},
        "drift_enabled": drift_enabled,
    }
    if run_id:
        event["run_id"] = run_id
    _append_event(event)

    state = _read_state()
    state["last_action"] = {
        "gene_id": selected_gene.get("id") if selected_gene else None,
        "action_id": action_id,
        "outcome_recorded": False,
        "ts": event["ts"],
    }
    _write_state(state)
    signal = cast(dict[str, Any], event.get("signal", {}))
    return {"actionId": action_id, "signalKey": signal["key"]}


def record_outcome(
    *,
    signals: list[str],
    selected_gene: dict[str, Any] | None,
    outcome: dict[str, Any],
    blast_radius: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "outcome",
        "id": _new_id("out"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "gene": selected_gene,
        "outcome": outcome,
        "blast_radius": blast_radius or {"files": 0, "lines": 0},
    }
    if run_id:
        event["run_id"] = run_id
    _append_event(event)

    state = _read_state()
    if "last_action" in state:
        state["last_action"]["outcome_recorded"] = True
    _write_state(state)
    return event


def record_external_candidate(
    *,
    asset: dict[str, Any] | None,
    source: str = "external",
    signals: list[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(asset, dict) or not asset.get("type") or not asset.get("id"):
        return None

    candidate: dict[str, Any] = {"type": asset["type"], "id": asset["id"]}
    if asset["type"] == "Capsule":
        candidate["trigger"] = list(asset.get("trigger", []))
        candidate["gene"] = asset.get("gene")
        candidate["confidence"] = asset.get("confidence")

    event = {
        "type": "MemoryGraphEvent",
        "kind": "external_candidate",
        "id": _new_id("ext"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "asset": {"type": asset["type"], "id": asset["id"]},
        "candidate": candidate,
        "external": {"source": source},
        "signal": {"key": compute_signal_key(signals or []), "signals": list(signals or [])},
    }
    return _append_event(event)


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        return cast(dict[str, Any], json.loads(raw))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_sync_state() -> dict[str, Any]:
    """Read cross-store sync metadata (living_memory ↔ memory_graph)."""
    sync = _read_state().get("sync")
    return dict(sync) if isinstance(sync, dict) else {}


def patch_sync_state(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge keys into ``memory_graph_state.json`` sync section."""
    state = _read_state()
    sync = state.setdefault("sync", {})
    if not isinstance(sync, dict):
        sync = {}
        state["sync"] = sync
    sync.update(updates)
    _write_state(state)
    return dict(sync)


def record_friction_observation(
    *,
    signals: list[str],
    friction: dict[str, Any],
    source: str = "living_memory",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Record a living-memory friction point as a memory_graph event."""
    event = {
        "type": "MemoryGraphEvent",
        "kind": "friction",
        "id": _new_id("fric"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "friction": {
            "id": friction.get("id"),
            "category": friction.get("category"),
            "description": str(friction.get("description", ""))[:300],
            "rule_id": friction.get("rule_id"),
        },
        "source": source,
    }
    if run_id:
        event["run_id"] = run_id
    return _append_event(event)


def record_signal_gene_preference(
    *,
    gene_id: str,
    signals: list[str],
    source: str = "solidify_success",
) -> dict[str, Any]:
    """Remember a gene that solidified successfully for a signal key."""
    key = compute_signal_key(signals)
    state = _read_state()
    prefs = state.setdefault("preferred_by_signal", {})
    if not isinstance(prefs, dict):
        prefs = {}
        state["preferred_by_signal"] = prefs
    entry = {
        "gene_id": gene_id,
        "source": source,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
    }
    prefs[key] = entry
    _write_state(state)
    return {"signalKey": key, **entry}


def get_memory_advice(
    *,
    signals: list[str] | None,
    genes: list[dict[str, Any]] | None,
    drift_enabled: bool = False,
) -> dict[str, Any]:
    signals = list(signals) if isinstance(signals, list) else []
    genes = list(genes) if isinstance(genes, list) else []
    key = compute_signal_key(signals)

    solidify_preferred: str | None = None
    prefs = _read_state().get("preferred_by_signal") or {}
    if isinstance(prefs, dict):
        pref_entry = prefs.get(key)
        if isinstance(pref_entry, dict) and pref_entry.get("gene_id"):
            solidify_preferred = str(pref_entry["gene_id"])

    events = try_read_memory_graph_events()
    outcomes = [e for e in events if e.get("kind") == "outcome"]
    friction_events = [e for e in events if e.get("kind") == "friction"]
    friction_cats: set[str] = set()
    for evt in friction_events:
        if evt.get("signal", {}).get("key") != key:
            continue
        fr = evt.get("friction") or {}
        cat = fr.get("category")
        if cat:
            friction_cats.add(str(cat))

    gene_stats: dict[str, dict[str, Any]] = {}
    for evt in outcomes:
        gene_id = evt.get("gene", {}).get("id") if evt.get("gene") else None
        if not gene_id:
            continue
        if evt.get("signal", {}).get("key") != key:
            continue
        stats = gene_stats.setdefault(gene_id, {"attempts": 0, "successes": 0, "failures": 0})
        stats["attempts"] += 1
        status = evt.get("outcome", {}).get("status")
        if status == "success":
            stats["successes"] += 1
        elif status == "failed":
            stats["failures"] += 1

    banned: set[str] = set()
    preferred: str | None = None
    best_rate = -1.0
    for gene_id, stats in gene_stats.items():
        if stats["attempts"] >= 3 and stats["failures"] / stats["attempts"] >= 0.8:
            banned.add(gene_id)
        if stats["attempts"] > 0:
            rate = stats["successes"] / stats["attempts"]
            if rate > best_rate:
                best_rate = rate
                preferred = gene_id

    if solidify_preferred and solidify_preferred not in banned:
        preferred = solidify_preferred

    explanation_parts = [
        f"signal_key={key}",
        f"matching_outcomes={len([e for e in outcomes if e.get('signal', {}).get('key') == key])}",
    ]
    if banned:
        explanation_parts.append(f"banned={','.join(banned)}")
    if solidify_preferred:
        explanation_parts.append(f"solidify_preferred={solidify_preferred}")
    if friction_cats:
        explanation_parts.append(f"friction_categories={','.join(sorted(friction_cats)[:5])}")

    return {
        "currentSignalKey": key,
        "preferredGeneId": preferred,
        "bannedGeneIds": banned,
        "solidifyPreferredGeneId": solidify_preferred,
        "frictionCategories": sorted(friction_cats),
        "explanation": "; ".join(explanation_parts),
    }


def read_all(limit: int = 10_000) -> list[dict[str, Any]]:
    """Alias for try_read_memory_graph_events (WebUI / observer API)."""
    return try_read_memory_graph_events(limit=limit)


__all__ = [
    "compute_signal_key",
    "get_memory_advice",
    "get_memory_graph_path",
    "read_all",
    "patch_sync_state",
    "read_sync_state",
    "record_attempt",
    "record_external_candidate",
    "record_friction_observation",
    "record_hypothesis",
    "record_outcome",
    "record_signal_gene_preference",
    "record_signal_snapshot",
    "try_read_memory_graph_events",
]
