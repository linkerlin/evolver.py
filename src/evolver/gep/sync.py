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
from evolver.gep.oauth_login import load_valid_oauth_access_token
from evolver.gep.sync_asset import install_sync_asset, prepare_sync_asset

logger = logging.getLogger(__name__)

_AUTH_REQUIRED_MSG = "sync requires an existing node_secret or a valid OAuth access token"


def _resolve_sync_auth(
    *,
    dry_run: bool,
    identity: dict[str, Any],  # noqa: ARG001 — reserved for future node-scoped OAuth
) -> dict[str, Any]:
    """Pick Authorization for published sync: node secret, else OAuth (dry-run).

    Dry-run never mints secrets; OAuth-only is accepted when the token file
    is present and not expired (syncOAuthDryRun).
    """
    headers = build_identity_hub_headers(create=not dry_run)
    if dry_run:
        headers = build_identity_hub_headers(create=False)

    if headers.get("Authorization"):
        return {"ok": True, "headers": headers, "auth": "node_secret"}

    oauth = load_valid_oauth_access_token()
    if oauth:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {oauth}",
        }
        return {"ok": True, "headers": headers, "auth": "oauth"}

    # Expired / missing OAuth: distinguish for clearer errors.
    from evolver.gep.paths import get_evolver_home  # noqa: PLC0415

    token_path = get_evolver_home() / "oauth_token.json"
    if token_path.is_file() and dry_run:
        return {"ok": False, "error": _AUTH_REQUIRED_MSG, "auth": "oauth_expired"}
    return {"ok": False, "error": _AUTH_REQUIRED_MSG, "auth": "missing"}


async def _sync_published_by_me(
    *,
    dry_run: bool,
    identity: dict[str, Any],
    force: bool = False,  # noqa: ARG001 — install uses force at caller
) -> dict[str, Any]:
    """GET /a2a/assets/published-by-me with the resolved identity tuple."""
    hub = (get_hub_url() or "").rstrip("/")
    if not hub:
        return {"ok": False, "error": "no_hub_url", "requests": []}

    auth = _resolve_sync_auth(dry_run=dry_run, identity=identity)
    if not auth.get("ok"):
        return {"ok": False, "error": auth.get("error"), "auth_failed": True}

    node_id = identity.get("node_id")
    headers = auth["headers"]

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
    force: bool = False,
) -> dict[str, Any]:
    """High-level sync: tasks / hub events / published-by-me (scope-aware).

    When *dry_run* is True the identity tuple is resolved **read-only**
    (no mint, no credential writes) so mixed mailbox/persisted identities
    cannot cross-contaminate disk state (identityTupleSync).

    *force* overwrites local Gene/Capsule id collisions when installing
    prepared Hub assets (syncAsset install path).
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
        pub = await _sync_published_by_me(dry_run=dry_run, identity=identity, force=force)
        if pub.get("auth_failed"):
            return {
                "ok": False,
                "error": pub.get("error") or _AUTH_REQUIRED_MSG,
                "installed": [],
                "errors": [str(pub.get("error") or _AUTH_REQUIRED_MSG)],
                "count": 0,
                "dry_run": dry_run,
                "scope": scope_norm,
            }
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
                    continue
                # Real sync: normalize via prepareSyncAsset then install.
                try:
                    from datetime import UTC, datetime  # noqa: PLC0415

                    synced_at = str(
                        asset.get("synced_at")
                        or asset.get("syncedAt")
                        or datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    )
                    prepared = prepare_sync_asset(
                        {
                            "assetType": asset.get("type") or "Gene",
                            "assetId": str(asset.get("asset_id") or asset.get("id") or "hub_asset"),
                            "localId": str(asset.get("id") or "local"),
                            "summary": str(asset.get("summary") or ""),
                            "syncedAt": synced_at,
                            "payload": asset,
                        }
                    )
                    result = install_sync_asset(prepared, force=force)
                    if result.get("ok"):
                        installed.append(result)
                    else:
                        errors.append(f"install {prepared.get('id')}: {result.get('error')}")
                except Exception as exc:
                    errors.append(f"prepare/install: {exc}")
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
            "force": force,
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
