"""A2A asset gate — blast-radius limits, broadcast eligibility, confidence scaling.

Equivalent to evolver/src/gep/a2a.js (173 lines).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
from datetime import UTC, datetime
from typing import Any

ALLOWED_A2A_ASSET_TYPES: frozenset[str] = frozenset({"Gene", "Capsule", "EvolutionEvent"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def is_allowed_a2a_asset(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return obj.get("type") in ALLOWED_A2A_ASSET_TYPES


def safe_number(x: Any, fallback: Any = None) -> Any:
    try:
        n = float(x)
    except (TypeError, ValueError):
        return fallback
    return n if math.isfinite(n) else fallback


def get_blast_radius_limits() -> dict[str, int]:
    raw_f = os.environ.get("A2A_MAX_FILES")
    raw_l = os.environ.get("A2A_MAX_LINES")
    mf = safe_number(raw_f, 5)
    ml = safe_number(raw_l, 200)
    if not isinstance(mf, (int, float)):
        mf = 5
    if not isinstance(ml, (int, float)):
        ml = 200
    return {"maxFiles": int(mf), "maxLines": int(ml)}


def is_blast_radius_safe(blast_radius: dict[str, Any] | None) -> bool:
    limits = get_blast_radius_limits()
    files = safe_number((blast_radius or {}).get("files"), 0) or 0
    lv = safe_number((blast_radius or {}).get("lines"), 0) or 0
    return files <= limits["maxFiles"] and lv <= limits["maxLines"]


def clamp01(n: Any) -> float:
    try:
        x = float(n)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def lower_confidence(
    asset: dict[str, Any] | None, opts: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if opts is None:
        opts = {}
    factor = float(opts.get("factor", 0.6))
    source = str(opts.get("source", "external"))
    received_at = str(opts.get("received_at", _now_iso()))
    cloned: dict[str, Any] = json.loads(json.dumps(asset or {}))
    if not is_allowed_a2a_asset(cloned):
        return None
    if cloned.get("type") == "Capsule":
        rc = cloned.get("confidence")
        if isinstance(rc, (int, float)):
            cloned["confidence"] = clamp01(rc * factor)
    a2a = cloned.get("a2a")
    if not isinstance(a2a, dict):
        a2a = {}
        cloned["a2a"] = a2a
    a2a["status"] = "external_candidate"
    a2a["source"] = source
    a2a["received_at"] = received_at
    a2a["confidence_factor"] = factor
    if not cloned.get("schema_version"):
        from evolver.gep.content_hash import SCHEMA_VERSION  # noqa: PLC0415
        cloned["schema_version"] = SCHEMA_VERSION
    if not cloned.get("asset_id"):
        try:
            from evolver.gep.content_hash import compute_asset_id  # noqa: PLC0415
            cloned["asset_id"] = compute_asset_id(cloned)
        except Exception:
            pass
    return cloned


def read_evolution_events() -> list[dict[str, Any]]:
    from evolver.gep.asset_store import read_all_events  # noqa: PLC0415
    events = read_all_events()
    return [e for e in events if isinstance(e, dict) and e.get("type") == "EvolutionEvent"]


def compute_capsule_success_streak(
    *, capsule_id: str | None = None, events: list[dict[str, Any]] | None = None
) -> int:
    eid = str(capsule_id) if capsule_id else ""
    if not eid:
        return 0
    evs = events if isinstance(events, list) else read_evolution_events()
    streak = 0
    for ev in reversed(evs):
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "EvolutionEvent":
            continue
        if str(ev.get("capsule_id") or ev.get("gene_id") or "") != eid:
            continue
        if str((ev.get("outcome") or {}).get("status", "unknown")) == "success":
            streak += 1
        else:
            break
    return streak


def is_capsule_broadcast_eligible(
    capsule: dict[str, Any] | None, opts: dict[str, Any] | None = None
) -> bool:
    if opts is None:
        opts = {}
    if not isinstance(capsule, dict) or capsule.get("type") != "Capsule":
        return False
    score = safe_number((capsule.get("outcome") or {}).get("score"), None)
    if score is None or score < 0.7:
        return False
    blast = capsule.get("blast_radius") or (capsule.get("outcome") or {}).get("blast_radius")
    if not is_blast_radius_safe(blast):
        return False
    evs = opts["events"] if isinstance(opts.get("events"), list) else read_evolution_events()
    return compute_capsule_success_streak(capsule_id=capsule.get("id"), events=evs) >= 2


def export_eligible_capsules(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if params is None:
        params = {}
    capsules = params["capsules"] if isinstance(params.get("capsules"), list) else []
    evs = params["events"] if isinstance(params.get("events"), list) else read_evolution_events()
    eligible = [
        c
        for c in capsules
        if isinstance(c, dict) and is_capsule_broadcast_eligible(c, {"events": evs})
    ]
    from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id  # noqa: PLC0415
    for c in eligible:
        if not c.get("schema_version"):
            c["schema_version"] = SCHEMA_VERSION
        if not c.get("asset_id"):
            with contextlib.suppress(Exception):
                c["asset_id"] = compute_asset_id(c)
    return eligible


def is_gene_broadcast_eligible(gene: dict[str, Any] | None) -> bool:
    if not isinstance(gene, dict) or gene.get("type") != "Gene":
        return False
    if not isinstance(gene.get("id"), str):
        return False
    s = gene.get("strategy")
    v = gene.get("validation")
    if not isinstance(s, list) or len(s) == 0:
        return False
    return bool(v) and isinstance(v, list) and len(v) > 0


def export_eligible_genes(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if params is None:
        params = {}
    genes = params["genes"] if isinstance(params.get("genes"), list) else []
    eligible = [g for g in genes if isinstance(g, dict) and is_gene_broadcast_eligible(g)]
    from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id  # noqa: PLC0415
    for g in eligible:
        if not g.get("schema_version"):
            g["schema_version"] = SCHEMA_VERSION
        if not g.get("asset_id"):
            with contextlib.suppress(Exception):
                g["asset_id"] = compute_asset_id(g)
    return eligible


def parse_a2a_input(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    try:
        from evolver.gep.a2a_protocol import unwrap_asset_from_message  # noqa: PLC0415
    except ImportError:
        def unwrap_asset_from_message(input_obj: Any) -> dict[str, Any] | None:
            return input_obj if isinstance(input_obj, dict) else None
    try:
        maybe = json.loads(raw)
        if isinstance(maybe, list):
            result: list[dict[str, Any]] = []
            for item in maybe:
                uw = unwrap_asset_from_message(item) or item
                if isinstance(uw, dict):
                    result.append(uw)
            return result
        if isinstance(maybe, dict):
            uw = unwrap_asset_from_message(maybe)
            return [uw] if isinstance(uw, dict) else [maybe]
    except (json.JSONDecodeError, TypeError):
        pass
    items: list[dict[str, Any]] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(line)
            uw = unwrap_asset_from_message(obj) or obj
            if isinstance(uw, dict):
                items.append(uw)
        except (json.JSONDecodeError, TypeError):
            continue
    return items


__all__ = [
    "ALLOWED_A2A_ASSET_TYPES",
    "clamp01",
    "compute_capsule_success_streak",
    "export_eligible_capsules",
    "export_eligible_genes",
    "get_blast_radius_limits",
    "is_allowed_a2a_asset",
    "is_blast_radius_safe",
    "is_capsule_broadcast_eligible",
    "is_gene_broadcast_eligible",
    "lower_confidence",
    "parse_a2a_input",
    "read_evolution_events",
    "safe_number",
]
