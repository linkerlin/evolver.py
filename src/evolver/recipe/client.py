"""Recipe Hub client — fetch and apply reusable project recipes.

A recipe is a declarative template (e.g., "fastapi-service",
"react-component-lib") that can be fetched from the Hub and applied
into the current workspace.
"""

from __future__ import annotations

from typing import Any

import httpx

from evolver.adapters.auth import load_auth
from evolver.config import HUB_SEARCH_TIMEOUT_MS, resolve_hub_url
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
) -> dict[str, Any]:
    """Fetch a single recipe by ID."""
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
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "recipe": data}


async def apply_recipe(
    recipe_id: str,
    target_dir: str = ".",
    dry_run: bool = False,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Fetch a recipe and stage its files into the target directory.

    This is a skeleton — a full implementation would:
      1. Download the recipe archive
      2. Validate checksums
      3. Render template variables
      4. Write files to disk
    """
    result = await get_recipe(recipe_id, hub_url)
    if not result.get("ok"):
        return result
    recipe = result["recipe"]
    if dry_run:
        return {"ok": True, "dry_run": True, "files": recipe.get("files", []), "recipe_id": recipe_id}
    return {"ok": True, "recipe_id": recipe_id, "applied": [], "note": "Recipe application is a skeleton in this port."}
