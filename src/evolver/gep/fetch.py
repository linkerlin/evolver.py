"""Fetch skills / genes / capsules from the EvoMap Hub.

Equivalent to evolver/src/gep/fetch.js.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.a2a_protocol import _http_post, get_hub_url
from evolver.gep.asset_store import (
    append_capsule,
    upsert_gene,
)
from evolver.gep.content_hash import compute_asset_id, verify_asset_id


async def search_assets(
    query: str,
    *,
    limit: int = 10,
    asset_type: str | None = None,
) -> dict[str, Any]:
    """Search the Hub for assets matching *query*."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url", "assets": []}
    payload: dict[str, Any] = {"query": query, "limit": limit}
    if asset_type:
        payload["type"] = asset_type
    try:
        result = await _http_post(f"{hub}/v1/a2a/search", payload)
        assets = result.get("assets", [])
        if not isinstance(assets, list):
            assets = []
        return {"ok": True, "assets": assets, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "assets": []}


async def download_asset(asset_id: str) -> dict[str, Any]:
    """Download a single asset by its content-addressed id."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url", "asset": None}
    try:
        result = await _http_post(f"{hub}/v1/a2a/assets", {"asset_id": asset_id})
        asset = result.get("asset")
        if not isinstance(asset, dict):
            return {"ok": False, "error": "invalid_asset_format", "asset": None}
        # Verify integrity if asset_id is a sha256:
        if asset_id.startswith("sha256:") and not verify_asset_id(asset, asset_id):
            return {"ok": False, "error": "asset_hash_mismatch", "asset": None}
        return {"ok": True, "asset": asset, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "asset": None}


def install_gene(asset: dict[str, Any]) -> dict[str, Any]:
    """Install a downloaded gene into the local asset store."""
    gene_id = asset.get("id")
    if not gene_id:
        return {"ok": False, "error": "missing_gene_id"}
    if asset.get("type") != "Gene":
        return {"ok": False, "error": "not_a_gene"}
    upsert_gene(asset)
    return {"ok": True, "gene_id": gene_id, "asset_id": compute_asset_id(asset)}


def install_capsule(asset: dict[str, Any]) -> dict[str, Any]:
    """Install a downloaded capsule into the local asset store."""
    cap_id = asset.get("id")
    if not cap_id:
        return {"ok": False, "error": "missing_capsule_id"}
    if asset.get("type") != "Capsule":
        return {"ok": False, "error": "not_a_capsule"}
    append_capsule(asset)
    return {"ok": True, "capsule_id": cap_id, "asset_id": compute_asset_id(asset)}


async def fetch_and_install(
    query: str,
    *,
    limit: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """High-level fetch: search Hub, optionally download and install top results."""
    search = await search_assets(query, limit=limit)
    if not search["ok"]:
        return {"ok": False, "error": search.get("error"), "installed": []}

    assets = search["assets"]
    if not assets:
        return {"ok": True, "installed": [], "message": "no_assets_found"}

    installed: list[dict[str, Any]] = []
    for asset in assets:
        if dry_run:
            installed.append(
                {
                    "id": asset.get("id"),
                    "type": asset.get("type"),
                    "action": "would_install",
                }
            )
            continue

        asset_type = asset.get("type")
        if asset_type == "Gene":
            result = install_gene(asset)
        elif asset_type == "Capsule":
            result = install_capsule(asset)
        else:
            result = {"ok": False, "error": f"unknown_type:{asset_type}"}

        if result["ok"]:
            installed.append(
                {
                    "id": result.get("gene_id") or result.get("capsule_id"),
                    "type": asset_type,
                    "asset_id": result.get("asset_id"),
                }
            )
        else:
            installed.append(
                {
                    "id": asset.get("id"),
                    "type": asset_type,
                    "error": result.get("error"),
                }
            )

    return {"ok": True, "installed": installed, "count": len(installed)}
