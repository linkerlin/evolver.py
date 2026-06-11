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


def serialize_assets(
    *,
    type_filter: str | None = None,
    page: int = 1,
    limit: int = 50,
    query: str | None = None,
    memory_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a paginated, filtered asset list for the WebUI."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    genes = _load_json(mem / "genes.json").get("genes", [])
    capsules = _load_json(mem / "capsules.json").get("capsules", [])

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
            if low in it.get("id", "").lower()
            or low in it.get("summary", "").lower()
            or low in it.get("description", "").lower()
        ]

    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    page_items = items[start:end]

    for it in page_items:
        if "file_path" in it:
            it["file_path"] = sanitize_path(it["file_path"])

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": page_items,
    }
