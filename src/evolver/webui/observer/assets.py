"""Asset serialization for WebUI — genes, capsules, candidates, lineage, call log.

Behavioral port of ``evolver/src/webui/observer/assets.js``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from evolver.gep.asset_call_log import get_log_path, read_call_log

from .paths import sanitize_path
from .redact import redact_text


def _load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _read_jsonl(path: Path, *, last: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    if isinstance(last, int) and last > 0:
        out = out[-last:]
    return out


def _merge_with_overlay(base: list[dict[str, Any]], overlay_path: Path) -> list[dict[str, Any]]:
    from evolver.gep.content_hash import verify_asset_id

    by_id: dict[str, dict[str, Any]] = {}
    for item in base:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    for row in _read_jsonl(overlay_path):
        if isinstance(row, dict) and row.get("id"):
            asset_id = row.get("asset_id")
            if asset_id and not verify_asset_id(row, asset_id):
                continue
            by_id[str(row["id"])] = row
    return list(by_id.values())


def _redact_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for key in ("summary", "description", "content", "message", "prompt"):
        if key in out and isinstance(out[key], str):
            out[key] = redact_text(out[key])
    return out


def _count_by(
    items: list[dict[str, Any]],
    key_or_fn: str | Callable[[dict[str, Any]], Any],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = key_or_fn(item) if callable(key_or_fn) else item.get(key_or_fn)
        safe = str(key or "unknown")
        counts[safe] = counts.get(safe, 0) + 1
    return counts


def _filter_text(items: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    if not query:
        return items
    needle = query.lower()
    return [it for it in items if needle in json.dumps(it, ensure_ascii=False).lower()]


def _paginate(items: list[dict[str, Any]], *, page: int = 1, limit: int = 50) -> dict[str, Any]:
    page = max(1, page)
    limit = max(1, min(limit, 500))
    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    return {"total": total, "page": page, "limit": limit, "items": items[start:end]}


def _matches_asset(item: dict[str, Any], asset_id: str) -> bool:
    if not asset_id:
        return False
    if item.get("id") == asset_id or item.get("asset_id") == asset_id:
        return True
    return item.get("asset_id") == f"sha256:{asset_id}"


def _event_mentions(event: dict[str, Any], asset_id: str) -> bool:
    if _matches_asset(event, asset_id):
        return True
    if event.get("capsule_id") == asset_id or event.get("mutation_id") == asset_id:
        return True
    if event.get("gene_id") == asset_id:
        return True
    genes_used = event.get("genes_used")
    return isinstance(genes_used, list) and asset_id in genes_used


def _read_genes(root: Path) -> list[dict[str, Any]]:
    base = _load_json(root / "genes.json").get("genes", [])
    if not isinstance(base, list):
        base = []
    return [_redact_item(g) for g in _merge_with_overlay(base, root / "genes.jsonl")]


def _read_capsules(root: Path) -> list[dict[str, Any]]:
    base = _load_json(root / "capsules.json").get("capsules", [])
    if not isinstance(base, list):
        base = []
    return [_redact_item(c) for c in _merge_with_overlay(base, root / "capsules.jsonl")]


def _read_failed_capsules(root: Path) -> list[dict[str, Any]]:
    data = _load_json(root / "failed_capsules.json")
    failed = data.get("failed_capsules") or data.get("capsules") or []
    if not isinstance(failed, list):
        return []
    return [_redact_item(dict(c, failed_store=True)) for c in failed if isinstance(c, dict)]


def serialize_assets(
    *,
    type_filter: str | None = None,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
    assets_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a paginated, filtered asset list for the WebUI."""
    from evolver.gep.paths import get_gep_assets_dir

    root = assets_dir or get_gep_assets_dir()
    genes = _read_genes(root)
    capsules = _read_capsules(root)

    items: list[dict[str, Any]] = []
    if type_filter in (None, "gene"):
        for g in genes:
            items.append({"type": "gene", **g})
    if type_filter in (None, "capsule"):
        for c in capsules:
            items.append({"type": "capsule", **c})

    items = _filter_text(items, query)
    page_data = _paginate(items, page=page, limit=limit)
    for it in page_data["items"]:
        if "file_path" in it:
            it["file_path"] = sanitize_path(it["file_path"])

    solid_count = sum(1 for g in genes if g.get("solidified"))
    return {
        **page_data,
        "counts": {
            "genes": len(genes),
            "capsules": len(capsules),
            "solidified": solid_count,
            "unsolidified": len(genes) - solid_count,
            "by_category": _count_by(genes, "category"),
            "by_outcome": _count_by(
                capsules,
                lambda c: (
                    (c.get("outcome") or {}).get("status")
                    if isinstance(c.get("outcome"), dict)
                    else "unknown"
                ),
            ),
        },
    }


def get_asset_overview(
    *,
    assets_dir: Path | None = None,
    events_last: int = 500,
    candidates_last: int = 200,
    asset_calls_last: int = 500,
) -> dict[str, Any]:
    """Dashboard overview: counts + recent events/calls (Node getAssetOverview)."""
    from evolver.gep.paths import get_gep_assets_dir

    root = assets_dir or get_gep_assets_dir()
    genes = _read_genes(root)
    capsules = _read_capsules(root)
    failed = _read_failed_capsules(root)
    events = [_redact_item(e) for e in _read_jsonl(root / "events.jsonl", last=events_last)]
    candidates = _read_jsonl(root / "candidates.jsonl", last=candidates_last)
    external = _read_jsonl(root / "external_candidates.jsonl", last=candidates_last)
    # Call log lives under evolution dir, not necessarily assets_dir
    calls = [_redact_item(c) for c in read_call_log({"last": asset_calls_last})]

    return {
        "counts": {
            "genes": len(genes),
            "capsules": len(capsules),
            "failedCapsules": len(failed),
            "events": len(events),
            "candidates": len(candidates),
            "externalCandidates": len(external),
            "assetCalls": len(calls),
        },
        "genesByCategory": _count_by(genes, "category"),
        "capsulesByOutcome": _count_by(
            capsules,
            lambda c: (
                (c.get("outcome") or {}).get("status")
                if isinstance(c.get("outcome"), dict)
                else "unknown"
            ),
        ),
        "assetCallsByAction": _count_by(calls, "action"),
        "recentEvents": list(reversed(events[-20:])),
        "recentAssetCalls": list(reversed(calls[-20:])),
    }


def list_candidates(
    *,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
    assets_dir: Path | None = None,
) -> dict[str, Any]:
    """Local + external candidates.jsonl with source tags."""
    from evolver.gep.paths import get_gep_assets_dir

    root = assets_dir or get_gep_assets_dir()
    local = [{**_redact_item(e), "source": "local"} for e in _read_jsonl(root / "candidates.jsonl")]
    external = [
        {**_redact_item(e), "source": "external"}
        for e in _read_jsonl(root / "external_candidates.jsonl")
    ]
    items = list(reversed(local + external))
    items = _filter_text(items, query)
    return _paginate(items, page=page, limit=limit)


def list_asset_calls(
    *,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
    run_id: str | None = None,
    action: str | None = None,
    last: int | None = None,
) -> dict[str, Any]:
    """Paginated asset call log (asset_call_log.jsonl)."""
    opts: dict[str, Any] = {}
    if run_id:
        opts["run_id"] = run_id
    if action:
        opts["action"] = action
    if last:
        opts["last"] = last
    calls = [_redact_item(c) for c in read_call_log(opts)]
    calls = list(reversed(calls))
    calls = _filter_text(calls, query)
    page_data = _paginate(calls, page=page, limit=limit)
    page_data["log_path"] = str(get_log_path())
    return page_data


def get_lineage(
    asset_id: str,
    *,
    assets_dir: Path | None = None,
) -> dict[str, Any]:
    """Gene/capsule/event/call-log lineage for an id or asset_id."""
    from evolver.gep.paths import get_gep_assets_dir

    root = assets_dir or get_gep_assets_dir()
    genes = _read_genes(root)
    capsules = _read_capsules(root) + _read_failed_capsules(root)
    events = [_redact_item(e) for e in _read_jsonl(root / "events.jsonl")]
    calls = [_redact_item(c) for c in read_call_log()]

    return {
        "id": asset_id,
        "genes": [g for g in genes if _matches_asset(g, asset_id)],
        "capsules": [
            c
            for c in capsules
            if _matches_asset(c, asset_id)
            or c.get("gene") == asset_id
            or c.get("gene_id") == asset_id
        ],
        "events": [e for e in events if _event_mentions(e, asset_id)],
        "assetCalls": [c for c in calls if _matches_asset(c, asset_id)],
    }
