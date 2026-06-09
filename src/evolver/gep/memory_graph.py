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
from typing import Any

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


def try_read_memory_graph_events(limit: int = 10_000) -> list[dict]:
    path = _graph_path()
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    break
    except OSError:
        return []
    return events


def _append_event(event: dict) -> dict:
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
    observations: dict | None = None,
    run_id: str | None = None,
) -> dict:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "signal",
        "id": _new_id("sig"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "observations": observations or {},
    }
    if run_id:
        event["run_id"] = run_id
    return _append_event(event)


def record_hypothesis(
    *,
    signals: list[str],
    selected_gene: dict | None,
    drift_enabled: bool = False,
    run_id: str | None = None,
) -> dict:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "hypothesis",
        "id": _new_id("hyp"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
        "signal": {"key": compute_signal_key(signals), "signals": list(signals)},
        "gene": selected_gene,
        "drift_enabled": drift_enabled,
    }
    if run_id:
        event["run_id"] = run_id
    _append_event(event)
    return {"hypothesisId": event["id"], "signalKey": event["signal"]["key"]}


def record_attempt(
    *,
    signals: list[str],
    selected_gene: dict | None,
    drift_enabled: bool = False,
    run_id: str | None = None,
) -> dict:
    action_id = _new_id("act")
    event = {
        "type": "MemoryGraphEvent",
        "kind": "attempt",
        "id": _new_id("att"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
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
    return {"actionId": action_id, "signalKey": event["signal"]["key"]}


def record_outcome(
    *,
    signals: list[str],
    selected_gene: dict | None,
    outcome: dict,
    blast_radius: dict | None = None,
    run_id: str | None = None,
) -> dict:
    event = {
        "type": "MemoryGraphEvent",
        "kind": "outcome",
        "id": _new_id("out"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
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
    asset: dict | None,
    source: str = "external",
    signals: list[str] | None = None,
) -> dict | None:
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
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
        "asset": {"type": asset["type"], "id": asset["id"]},
        "candidate": candidate,
        "external": {"source": source},
        "signal": {"key": compute_signal_key(signals or []), "signals": list(signals or [])},
    }
    return _append_event(event)


def _read_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_memory_advice(
    *,
    signals: list[str] | None,
    genes: list[dict] | None,
    drift_enabled: bool = False,
) -> dict[str, Any]:
    signals = list(signals) if isinstance(signals, list) else []
    genes = list(genes) if isinstance(genes, list) else []
    key = compute_signal_key(signals)

    events = try_read_memory_graph_events()
    outcomes = [e for e in events if e.get("kind") == "outcome"]

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

    explanation_parts = [f"signal_key={key}", f"matching_outcomes={len([e for e in outcomes if e.get('signal', {}).get('key') == key])}"]
    if banned:
        explanation_parts.append(f"banned={','.join(banned)}")

    return {
        "currentSignalKey": key,
        "preferredGeneId": preferred,
        "bannedGeneIds": banned,
        "explanation": "; ".join(explanation_parts),
    }


__all__ = [
    "compute_signal_key",
    "try_read_memory_graph_events",
    "record_signal_snapshot",
    "record_hypothesis",
    "record_attempt",
    "record_outcome",
    "record_external_candidate",
    "get_memory_advice",
]
