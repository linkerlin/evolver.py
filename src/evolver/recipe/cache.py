"""Local recipe cache for offline application.

Recipes fetched from the Hub are persisted to disk so they can be
applied without network connectivity.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _cache_dir() -> Path:
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / "recipe_cache"


def _recipe_cache_path(recipe_id: str) -> Path:
    return _cache_dir() / f"{recipe_id}.json"


def cache_recipe(recipe: dict[str, Any]) -> None:
    """Persist a recipe to the local cache."""
    path = _recipe_cache_path(recipe.get("id", "unknown"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")


def get_cached_recipe(recipe_id: str) -> dict[str, Any] | None:
    """Load a recipe from the local cache if present."""
    path = _recipe_cache_path(recipe_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_cached_recipes() -> list[dict[str, Any]]:
    """List all cached recipes."""
    d = _cache_dir()
    if not d.exists():
        return []
    recipes: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        try:
            recipes.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return recipes


def clear_cache() -> int:
    """Remove all cached recipes. Returns count deleted."""
    d = _cache_dir()
    if not d.exists():
        return 0
    count = 0
    for p in d.glob("*.json"):
        try:
            p.unlink()
            count += 1
        except OSError:
            continue
    return count
