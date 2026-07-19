"""Asset serialization for WebUI — genes, capsules, filtering, pagination."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .paths import sanitize_path


def _load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
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

    genes_base = _load_json(root / "genes.json").get("genes", [])
    genes = _merge_with_overlay(genes_base, root / "genes.jsonl")
    capsules_base = _load_json(root / "capsules.json").get("capsules", [])
    capsules = _merge_with_overlay(capsules_base, root / "capsules.jsonl")

    items: list[dict[str, Any]] = []
    if type_filter in (None, "gene"):
        for g in genes:
            items.append({"type": "gene", **g})
    if type_filter in (None, "capsule"):
        for c in capsules:
            items.append({"type": "capsule", **c})

    if query:
        low = query.lower()
        items = [
            it
            for it in items
            if low in str(it.get("id", "")).lower()
            or low in str(it.get("summary", "")).lower()
            or low in str(it.get("description", "")).lower()
        ]

    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    page_items = items[start:end]

    for it in page_items:
        if "file_path" in it:
            it["file_path"] = sanitize_path(it["file_path"])

    solid_count = sum(1 for g in genes if g.get("solidified"))
    unsolid_count = len(genes) - solid_count

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": page_items,
        "counts": {
            "genes": len(genes),
            "capsules": len(capsules),
            "solidified": solid_count,
            "unsolidified": unsolid_count,
        },
    }
