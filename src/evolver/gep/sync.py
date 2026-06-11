"""Sync assets from the EvoMap Hub.

Equivalent to evolver/src/gep/sync.js.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.a2a_protocol import consume_hub_events, fetch_tasks
from evolver.gep.fetch import download_asset, install_capsule, install_gene


async def sync_all(
    *,
    dry_run: bool = False,
    scope: str | None = None,
) -> dict[str, Any]:
    """High-level sync: fetch tasks and hub events, install matching assets."""
    installed: list[dict[str, Any]] = []
    errors: list[str] = []

    # Fetch tasks
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
            # Tasks are not installed into asset store; they are ephemeral
            installed.append(
                {
                    "id": task.get("task_id"),
                    "type": "Task",
                    "action": "noted",
                }
            )
    else:
        errors.append(f"tasks: {tasks_result.get('error')}")

    # Consume hub events for directives to fetch assets
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
    }
