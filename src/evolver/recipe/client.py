"""Recipe Hub client — fetch and apply reusable project recipes.

A recipe is a declarative template (e.g., "fastapi-service",
"react-component-lib") that can be fetched from the Hub and applied
into the current workspace.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from evolver.adapters.auth import load_auth
from evolver.config import resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers


def _recipe_url(hub_url: str, path: str) -> str:
    return f"{hub_url}/v1/recipes/{path}"


def _auth_headers() -> dict[str, str]:
    headers = build_hub_headers()
    auth = load_auth()
    if auth:
        headers["Authorization"] = f"Bearer {auth['access_token']}"
    return headers


async def list_recipes(
    tag: str | None = None,
    limit: int = 20,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """List available recipes from the Hub."""
    hub = hub_url or resolve_hub_url()
    params: dict[str, Any] = {"limit": limit}
    if tag:
        params["tag"] = tag
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.get(
                _recipe_url(hub, ""),
                params=params,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "recipes": data.get("recipes", [])}


async def get_recipe(
    recipe_id: str,
    hub_url: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch a single recipe by ID, caching on success and falling back on failure."""
    from evolver.recipe.cache import cache_recipe, get_cached_recipe

    hub = hub_url or resolve_hub_url()
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.get(
                _recipe_url(hub, recipe_id),
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        if use_cache:
            cached = get_cached_recipe(recipe_id)
            if cached:
                return {"ok": True, "recipe": cached, "source": "cache"}
        return {"ok": False, "error": str(exc)}

    if use_cache:
        cache_recipe(data)
    return {"ok": True, "recipe": data, "source": "hub"}


_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render_template(content: str, variables: dict[str, str]) -> str:
    """Replace {{var}} placeholders with provided values."""

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _TEMPLATE_VAR_RE.sub(replacer, content)


async def apply_recipe(
    recipe_id: str,
    target_dir: str = ".",
    dry_run: bool = False,
    variables: dict[str, str] | None = None,
    hub_url: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch a recipe and stage its files into the target directory.

    Supports simple {{var}} template rendering and conflict detection.
    Falls back to local cache if Hub is unreachable.
    """
    result = await get_recipe(recipe_id, hub_url, use_cache=use_cache)
    if not result.get("ok"):
        return result
    recipe = result["recipe"]
    files = recipe.get("files", [])
    if not files:
        return {
            "ok": True,
            "recipe_id": recipe_id,
            "applied": [],
            "note": "Recipe contains no files.",
        }

    base = Path(target_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)

    # Build variable map from recipe defaults + user overrides
    merged_vars: dict[str, str] = {}
    for v in recipe.get("variables", []):
        merged_vars[v["name"]] = v.get("default", "")
    if variables:
        merged_vars.update(variables)

    applied: list[str] = []
    conflicts: list[str] = []

    for f in files:
        rel_path = f["path"].lstrip("/")
        target = base / rel_path
        rendered = _render_template(f.get("content", ""), merged_vars)

        if dry_run:
            continue

        if target.exists():
            conflicts.append(rel_path)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        applied.append(rel_path)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "recipe_id": recipe_id,
            "files": [f["path"] for f in files],
            "variables": merged_vars,
        }

    return {
        "ok": True,
        "recipe_id": recipe_id,
        "applied": applied,
        "conflicts": conflicts,
        "variables": merged_vars,
    }
