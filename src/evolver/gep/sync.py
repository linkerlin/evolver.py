"""Sync assets from the EvoMap Hub.

Equivalent to evolver/src/gep/sync.js (+ identity-tuple isolation for
``published`` scope / ``--dry-run`` from v1.92.0).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from evolver.gep.a2a_protocol import consume_hub_events, fetch_tasks, get_hub_url
from evolver.gep.fetch import download_asset, install_capsule, install_gene
from evolver.gep.node_identity import (
    build_identity_hub_headers,
    resolve_identity_tuple,
    resolve_readonly_node_id,
)

logger = logging.getLogger(__name__)


async def _sync_published_by_me(
    *,
    dry_run: bool,
    identity: dict[str, Any],
) -> dict[str, Any]:
    """GET /a2a/assets/published-by-me with the resolved identity tuple."""
    hub = (get_hub_url() or "").rstrip("/")
    if not hub:
        return {"ok": False, "error": "no_hub_url", "requests": []}

    node_id = identity.get("node_id")
    headers = build_identity_hub_headers(create=not dry_run)
    # dry-run rebuilds headers without create; ensure readonly tuple used.
    if dry_run:
        headers = build_identity_hub_headers(create=False)

    params: dict[str, str] = {}
    if node_id:
        params["node_id"] = str(node_id)

    # Prefer short path used by Node identityTupleSync tests; also try /v1.
    urls = [
        f"{hub}/a2a/assets/published-by-me",
        f"{hub}/v1/a2a/assets/published-by-me",
    ]
    last_error: str | None = None
    for url in urls:
        try:
            async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 404 and url.endswith("/v1/a2a/assets/published-by-me"):
                    last_error = "404"
                    continue
                if response.status_code == 404:
                    last_error = "404"
                    continue
                response.raise_for_status()
                body = response.json() if response.content else {}
                assets = body.get("assets") if isinstance(body, dict) else []
                return {
                    "ok": True,
                    "assets": assets if isinstance(assets, list) else [],
                    "node_id": node_id,
                    "url": url,
                    "status_code": response.status_code,
                }
        except Exception as exc:
            last_error = str(exc)
            logger.debug("[sync] published-by-me via %s failed: %s", url, exc)
    return {"ok": False, "error": last_error or "published_by_me_failed", "requests": []}


async def sync_all(  # noqa: PLR0912, PLR0915
    *,
    dry_run: bool = False,
    scope: str | None = None,
) -> dict[str, Any]:
    """High-level sync: tasks / hub events / published-by-me (scope-aware).

    When *dry_run* is True the identity tuple is resolved **read-only**
    (no mint, no credential writes) so mixed mailbox/persisted identities
    cannot cross-contaminate disk state (identityTupleSync).
    """
    installed: list[dict[str, Any]] = []
    errors: list[str] = []

    # Resolve identity once; dry-run never creates or rewrites identity files.
    if dry_run:
        identity = resolve_identity_tuple(create=False)
        # Ensure we did not mint: readonly path only.
        if identity.get("node_id") is None:
            identity = {
                "node_id": resolve_readonly_node_id(),
                "secret": identity.get("secret"),
                "version": identity.get("version"),
            }
    else:
        identity = resolve_identity_tuple(create=True)

    scope_norm = (scope or "").strip().lower()
    if scope_norm in ("published", "published-by-me", "mine"):
        pub = await _sync_published_by_me(dry_run=dry_run, identity=identity)
        if pub.get("ok"):
            for asset in pub.get("assets") or []:
                if not isinstance(asset, dict):
                    continue
                if dry_run:
                    installed.append(
                        {
                            "id": asset.get("id") or asset.get("asset_id"),
                            "type": asset.get("type"),
                            "action": "would_sync",
                        }
                    )
                else:
                    installed.append(
                        {
                            "id": asset.get("id") or asset.get("asset_id"),
                            "type": asset.get("type"),
                            "action": "listed",
                        }
                    )
        else:
            errors.append(f"published: {pub.get('error')}")
        return {
            "ok": True,
            "installed": installed,
            "errors": errors,
            "count": len(installed),
            "identity": {
                "node_id": identity.get("node_id"),
                # Never echo secrets in results.
                "has_secret": bool(identity.get("secret")),
                "version": identity.get("version"),
            },
            "dry_run": dry_run,
            "scope": scope_norm,
        }

    # Default path: tasks + hub events (pre-existing behaviour).
    tasks_result = await fetch_tasks(limit=20)
    if tasks_result.get("ok"):
        for task in tasks_result.get("tasks", []):
            if dry_run:
                installed.append(
                    {
                        "id": task.get("task_id"),
                        "type": "Task",
                        "action": "would_sync",
                    }
                )
                continue
            installed.append(
                {
                    "id": task.get("task_id"),
                    "type": "Task",
                    "action": "noted",
                }
            )
    else:
        errors.append(f"tasks: {tasks_result.get('error')}")

    events_result = await consume_hub_events(max_events=50)
    if events_result.get("ok"):
        for evt in events_result.get("events", []):
            directive = evt.get("directive") or evt.get("body", "")
            asset_id = evt.get("asset_id")
            if asset_id:
                dl = await download_asset(asset_id)
                if not dl.get("ok"):
                    errors.append(f"download {asset_id}: {dl.get('error')}")
                    continue
                asset = dl["asset"]
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
                    errors.append(f"install {asset.get('id')}: {result.get('error')}")
            else:
                installed.append(
                    {
                        "type": "Event",
                        "action": "noted",
                        "body": directive[:200] if isinstance(directive, str) else "",
                    }
                )
    else:
        errors.append(f"events: {events_result.get('error')}")

    return {
        "ok": True,
        "installed": installed,
        "errors": errors,
        "count": len(installed),
        "identity": {
            "node_id": identity.get("node_id"),
            "has_secret": bool(identity.get("secret")),
            "version": identity.get("version"),
        },
        "dry_run": dry_run,
    }
