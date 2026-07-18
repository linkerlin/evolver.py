"""Local memory graph store and query engine.

Equivalent to evolver/src/gep/memoryGraph.js (obfuscated).

Includes memory_graph.jsonl rotation (#519): when the active file exceeds
``EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB`` (default 100 MB), it is renamed and
gzip-compressed; at most ``EVOLVER_MEMORY_GRAPH_RETENTION_COUNT`` (default 7)
archives are kept. Opt out with ``EVOLVER_MEMORY_GRAPH_AUTO_ROTATE=false``.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import math
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from evolver.config import GENE_INERT_BAN_STREAK
from evolver.gep.paths import get_evolution_dir, get_memory_graph_path

# --- Rotation (#519) --------------------------------------------------------

ROTATE_CHECK_INTERVAL_MS: float = 30_000
ROTATE_CHECK_WRITES: int = 100
_DEFAULT_MAX_SIZE_MB: float = 100.0
_DEFAULT_RETENTION: int = 7
_DEFAULT_GZIP_MAX_MB: float = 32.0

# Matches both legacy ``.<ts>`` and current ``.<ts>.gz`` archive forms.
_ROTATED_SUFFIX_RE = re.compile(r"\.(\d{8,})(?:\.gz)?$")

# Throttle state for maybe_rotate (mirrors Node module-level counters).
_rotate_throttle: dict[str, float | int] = {
    "last_check_at": 0.0,
    "writes_since_check": 0,
}

# Outcome notes that indicate a zero-work ("inert") success — the gene ran but
# produced no real artifact. These must NOT build Bayesian confidence, and a
# gene whose trailing history is entirely inert must be banned so the selector
# falls through to mutation (EvoMap/evolver#562).
_INERT_NOTE_MARKERS: tuple[str, ...] = (
    "stable_no_error",
    "heuristic_delta",
    "predictive",
)


def _is_inert_outcome(outcome: dict[str, Any]) -> bool:
    """Return True if a success outcome is actually zero-work (inert).

    An outcome counts as inert when ``status == 'success'`` but the ``note``
    indicates no real error was cleared / no artifact produced.  Inert
    outcomes build no confidence and accumulate a consecutive-trailing streak
    that, once it reaches :data:`GENE_INERT_BAN_STREAK`, bans the gene (#562).
    """
    if str(outcome.get("status", "")).lower() != "success":
        return False
    note = str(outcome.get("note", "")).lower()
    return any(marker in note for marker in _INERT_NOTE_MARKERS)


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


def rotation_enabled() -> bool:
    """Return whether auto-rotation is enabled (env-driven, default true)."""
    raw = str(os.environ.get("EVOLVER_MEMORY_GRAPH_AUTO_ROTATE", "true")).lower()
    return raw not in ("false", "0", "no")


def rotation_max_size_bytes() -> int:
    """Max active-file size in bytes before rotation (default 100 MB)."""
    raw = os.environ.get("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB")
    try:
        mb = float(raw) if raw is not None and raw != "" else float("nan")
    except (TypeError, ValueError):
        mb = float("nan")
    safe = mb if math.isfinite(mb) and mb > 0 else _DEFAULT_MAX_SIZE_MB
    return int(safe * 1024 * 1024)


def rotation_retention_count() -> int:
    """How many rotated archives to keep (default 7; 0 deletes all)."""
    raw = os.environ.get("EVOLVER_MEMORY_GRAPH_RETENTION_COUNT")
    try:
        n = float(raw) if raw is not None and raw != "" else float("nan")
    except (TypeError, ValueError):
        n = float("nan")
    if math.isfinite(n) and n >= 0:
        return int(n)
    return _DEFAULT_RETENTION


def _gzip_max_bytes() -> int:
    raw = os.environ.get("EVOLVER_ROTATE_GZIP_MAX_MB")
    try:
        mb = float(raw) if raw is not None and raw != "" else float("nan")
    except (TypeError, ValueError):
        mb = float("nan")
    safe = mb if math.isfinite(mb) and mb > 0 else _DEFAULT_GZIP_MAX_MB
    return int(safe * 1024 * 1024)


def prune_rotated_archives(active_path: Path | str, retention: int | None = None) -> None:
    """Delete oldest rotated archives beyond *retention* (newest kept)."""
    if retention is None:
        retention = rotation_retention_count()
    try:
        active = Path(active_path)
        directory = active.parent
        base_name = active.name
        prefix = base_name + "."
        entries: list[tuple[str, int]] = []
        for name in os.listdir(directory):
            if not name.startswith(prefix):
                continue
            # Match suffix on the part after basename.
            rest = name[len(base_name) :]
            m = _ROTATED_SUFFIX_RE.match(rest)
            if not m:
                continue
            entries.append((name, int(m.group(1))))
        entries.sort(key=lambda x: x[1], reverse=True)
        for name, _ts in entries[retention:]:
            with contextlib.suppress(OSError):
                (directory / name).unlink(missing_ok=True)
    except OSError:
        pass


def rotate_memory_graph_now(active_path: Path | str | None = None) -> str | None:
    """Force-rotate the active graph file; return archive path or None."""
    path = Path(active_path) if active_path is not None else _graph_path()
    renamed_to: str | None = None
    try:
        if not path.exists():
            return None
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        rotated = Path(f"{path}.{ts}")
        # Atomic rename on same filesystem; new writes recreate active path.
        path.replace(rotated)
        renamed_to = str(rotated)

        # Compress to .gz unless file exceeds OOM guard threshold.
        try:
            skip_gzip = False
            with contextlib.suppress(OSError):
                if rotated.stat().st_size > _gzip_max_bytes():
                    skip_gzip = True
            if not skip_gzip:
                raw = rotated.read_bytes()
                gz_path = Path(f"{rotated}.gz")
                with gzip.open(gz_path, "wb") as gz_handle:
                    gz_handle.write(raw)
                with contextlib.suppress(OSError):
                    rotated.unlink(missing_ok=True)
                renamed_to = str(gz_path)
        except OSError:
            # Keep uncompressed rotated file as fallback.
            pass

        prune_rotated_archives(path, rotation_retention_count())
    except OSError:
        # Rotation failure must never break evolver's write path.
        return renamed_to
    return renamed_to


def maybe_rotate_memory_graph(
    active_path: Path | str | None = None,
    *,
    force: bool = False,
) -> str | None:
    """Rotate when size exceeds threshold (throttled unless *force*)."""
    if not rotation_enabled():
        return None

    writes = int(_rotate_throttle["writes_since_check"]) + 1
    _rotate_throttle["writes_since_check"] = writes
    now_ms = time.time() * 1000.0
    last_check = float(_rotate_throttle["last_check_at"])
    if (
        not force
        and writes < ROTATE_CHECK_WRITES
        and (now_ms - last_check) < ROTATE_CHECK_INTERVAL_MS
    ):
        return None

    _rotate_throttle["writes_since_check"] = 0
    _rotate_throttle["last_check_at"] = now_ms

    path = Path(active_path) if active_path is not None else _graph_path()
    try:
        if not path.exists():
            return None
        if path.stat().st_size < rotation_max_size_bytes():
            return None
        return rotate_memory_graph_now(path)
    except OSError:
        return None


def rotate_on_startup_if_oversized() -> str | None:
    """Force rotation if the active file is already oversized (boot path)."""
    try:
        if not rotation_enabled():
            return None
        path = _graph_path()
        if not path.exists():
            return None
        if path.stat().st_size >= rotation_max_size_bytes():
            return rotate_memory_graph_now(path)
    except OSError:
        return None
    return None


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
    # Best-effort rotation after write (#519); never raise.
    with contextlib.suppress(Exception):
        maybe_rotate_memory_graph(path)
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


def _count_trailing_inert(
    outcomes: list[dict[str, Any]], signal_key: str, gene_id: str
) -> tuple[int, bool]:
    """Count consecutive trailing inert outcomes for *gene_id* on *signal_key*.

    Walks the chronological outcome list (oldest→newest) and counts how many
    of the *trailing* (most-recent) entries are inert.  A single real success
    or failure breaks the inert streak.

    Returns ``(trailing_inert_count, has_any_real_success)``.
    """
    relevant: list[dict[str, Any]] = []
    has_real_success = False
    for evt in outcomes:
        if evt.get("signal", {}).get("key") != signal_key:
            continue
        g = evt.get("gene")
        if not g or g.get("id") != gene_id:
            continue
        outcome = evt.get("outcome") or {}
        relevant.append(outcome)
        if outcome.get("status") == "success" and not _is_inert_outcome(outcome):
            has_real_success = True

    # Count trailing inert (iterate newest→oldest).
    trailing = 0
    for outcome in reversed(relevant):
        if _is_inert_outcome(outcome):
            trailing += 1
        else:
            break
    return trailing, has_real_success


def get_memory_advice(  # noqa: PLR0912, PLR0915
    *,
    signals: list[str] | None,
    genes: list[dict[str, Any]] | None,
    drift_enabled: bool = False,  # noqa: ARG001
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
        outcome = evt.get("outcome") or {}
        status = outcome.get("status")
        if status == "success" and not _is_inert_outcome(outcome):
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

    # #562: a gene whose trailing outcomes are ALL inert (zero-work) must not
    # be preferred — it climbed to p~1.0 on non-evidence.  Additionally, ban a
    # gene after GENE_INERT_BAN_STREAK consecutive trailing inert outcomes with
    # no real success, so the selector yields null and the pipeline mutates.
    for gene_id in list(gene_stats):
        trailing_inert, has_real_success = _count_trailing_inert(outcomes, key, gene_id)
        if has_real_success:
            # Real work was done — never punish old idle cycles.
            continue
        # No real success at all: if *every* outcome is inert, don't prefer.
        attempts = gene_stats[gene_id]["attempts"]
        if 0 < attempts <= trailing_inert and preferred == gene_id:
            preferred = None
        if trailing_inert >= GENE_INERT_BAN_STREAK:
            banned.add(gene_id)

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


# Boot-time rotation: if a pre-rotation evolver left an oversized file, rotate
# once at import. Best-effort; never raises.
with contextlib.suppress(Exception):
    rotate_on_startup_if_oversized()


__all__ = [
    "compute_signal_key",
    "get_memory_advice",
    "get_memory_graph_path",
    "maybe_rotate_memory_graph",
    "patch_sync_state",
    "prune_rotated_archives",
    "read_all",
    "read_sync_state",
    "record_attempt",
    "record_external_candidate",
    "record_friction_observation",
    "record_hypothesis",
    "record_outcome",
    "record_signal_gene_preference",
    "record_signal_snapshot",
    "rotate_memory_graph_now",
    "rotate_on_startup_if_oversized",
    "rotation_enabled",
    "rotation_max_size_bytes",
    "rotation_retention_count",
    "try_read_memory_graph_events",
]
