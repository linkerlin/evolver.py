"""Proxy REST route matrix.

Equivalent to ``evolver/src/proxy/server/routes.js``.
Mounts mailbox, asset, task, DM, session, proxy, ATP, and LLM routes
on a FastAPI router.

Authentication
--------------
All routes (except ``/proxy/status``) require ``Authorization: Bearer <token>``.
The token is read from ``~/.evomap/proxy-token`` or ``EVOMAP_PROXY_TOKEN``.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from evolver.gep.content_hash import verify_asset_id
from evolver.gep.schemas.capsule import Capsule, validate_capsule
from evolver.gep.schemas.gene import Gene, validate_gene
from evolver.proxy.extensions.dm_handler import DMHandler
from evolver.proxy.extensions.session_handler import SessionHandler
from evolver.proxy.extensions.skill_updater import SkillUpdater
from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.router.messages_route import handle_messages
from evolver.proxy.task.monitor import TaskMonitor

router = APIRouter()

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _load_proxy_token() -> str | None:
    env = os.environ.get("EVOMAP_PROXY_TOKEN", "").strip()
    if env:
        return env
    token_file = __import__("pathlib").Path.home() / ".evomap" / "proxy-token"
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        return token or None
    return None


async def require_auth(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header[7:].strip()
    expected = _load_proxy_token()
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(request: Request) -> MailboxStore:
    store: MailboxStore | None = getattr(request.app.state, "mailbox_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Mailbox store not initialized")
    return store


def _get_session_handler(request: Request) -> SessionHandler:
    handler: SessionHandler | None = getattr(request.app.state, "session_handler", None)
    if handler is None:
        raise HTTPException(status_code=503, detail="Session handler not initialized")
    return handler


def _get_skill_updater(request: Request) -> SkillUpdater:
    updater: SkillUpdater | None = getattr(request.app.state, "skill_updater", None)
    if updater is None:
        raise HTTPException(status_code=503, detail="Skill updater not initialized")
    return updater


def _get_task_monitor(request: Request) -> TaskMonitor:
    monitor: TaskMonitor | None = getattr(request.app.state, "task_monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Task monitor not initialized")
    return monitor


def _get_dm_handler(request: Request) -> DMHandler | None:
    return getattr(request.app.state, "dm_handler", None)


def _get_atp_orders(request: Request) -> dict[str, Any]:
    orders: dict[str, Any] | None = getattr(request.app.state, "atp_orders", None)
    if orders is None:
        orders = {}
        request.app.state.atp_orders = orders
    return orders


def _get_claimed_tasks(request: Request) -> dict[str, Any]:
    claimed: dict[str, Any] | None = getattr(request.app.state, "claimed_tasks", None)
    if claimed is None:
        claimed = {}
        request.app.state.claimed_tasks = claimed
    return claimed


# ---------------------------------------------------------------------------
# Mailbox
# ---------------------------------------------------------------------------


@router.post("/mailbox/send")
async def mailbox_send(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    result = store.send(
        type=body.get("type", ""),
        payload=body.get("payload", {}),
        channel=body.get("channel", "evomap-hub"),
        priority=body.get("priority", "normal"),
        ref_id=body.get("ref_id"),
    )
    return JSONResponse(result)


@router.post("/mailbox/poll")
async def mailbox_poll(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    msgs = store.poll(
        channel=body.get("channel"),
        type=body.get("type"),
        limit=body.get("limit", 100),
    )
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


@router.post("/mailbox/ack")
async def mailbox_ack(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    count = store.ack(body.get("message_ids", []))
    return JSONResponse({"acked": count})


@router.get("/mailbox/list")
async def mailbox_list(
    request: Request,
    type: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    msgs = store.list(
        type=type,
        direction=direction,  # type: ignore[arg-type]
        status=status,
        limit=limit,
        offset=offset,
    )
    return JSONResponse({"messages": [m.to_dict() for m in msgs], "total": len(msgs)})


@router.get("/mailbox/status/{msg_id}")
async def mailbox_status(
    request: Request,
    msg_id: str,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    msg = store.get_by_id(msg_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return JSONResponse(msg.to_dict())


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@router.post("/asset/validate")
async def asset_validate(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    payload = body.get("payload") or body.get("asset") or body
    if not isinstance(payload, dict):
        return JSONResponse(
            {"valid": False, "errors": ["payload must be an object"]}, status_code=400
        )

    asset_type = payload.get("type")
    try:
        if asset_type == "Gene":
            gene = Gene.model_validate(payload)
            validate_gene(gene)
            if gene.asset_id and not verify_asset_id(payload, gene.asset_id):
                return JSONResponse({"valid": False, "errors": ["asset_id hash mismatch"]})
        elif asset_type == "Capsule":
            capsule = Capsule.model_validate(payload)
            validate_capsule(capsule)
            if capsule.asset_id and not verify_asset_id(payload, capsule.asset_id):
                return JSONResponse({"valid": False, "errors": ["asset_id hash mismatch"]})
        else:
            return JSONResponse(
                {"valid": False, "errors": [f"unknown or missing asset type: {asset_type!r}"]},
                status_code=400,
            )
    except (ValidationError, ValueError) as exc:
        errors = exc.errors() if isinstance(exc, ValidationError) else [str(exc)]
        return JSONResponse({"valid": False, "errors": errors})

    return JSONResponse({"valid": True})


@router.post("/asset/fetch")
async def asset_fetch(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    """Fetch an asset from the Hub (by asset_id) or a direct URL."""
    import httpx

    from evolver.gep import fetch as gep_fetch

    asset_id = str(body.get("asset_id", "")).strip()
    url = str(body.get("url", "")).strip()
    install = bool(body.get("install", False))

    if asset_id:
        result = await gep_fetch.download_asset(asset_id)
        if not result.get("ok"):
            status = 404 if result.get("error") == "no_hub_url" else 502
            return JSONResponse(result, status_code=status)
        asset = result.get("asset")
        payload: dict[str, Any] = {
            "ok": True,
            "source": "hub",
            "asset_id": asset_id,
            "asset": asset,
        }
        if install and isinstance(asset, dict):
            asset_type = asset.get("type")
            if asset_type == "Gene":
                payload["install"] = gep_fetch.install_gene(asset)
            elif asset_type == "Capsule":
                payload["install"] = gep_fetch.install_capsule(asset)
            else:
                payload["install"] = {"ok": False, "error": f"unknown_type:{asset_type}"}
        return JSONResponse(payload)

    if not url:
        return JSONResponse({"ok": False, "error": "missing_asset_id_or_url"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return JSONResponse(
                {"ok": False, "error": "upstream_fetch_failed", "status": resp.status_code},
                status_code=502,
            )
        content_type = resp.headers.get("content-type", "unknown")
        payload = {
            "ok": True,
            "source": "url",
            "url": url,
            "content_length": len(resp.content),
            "content_type": content_type,
        }
        if content_type.startswith("application/json"):
            try:
                payload["json"] = resp.json()
            except Exception:
                pass
        return JSONResponse(payload)
    except httpx.TimeoutException:
        return JSONResponse({"ok": False, "error": "fetch_timeout"}, status_code=504)
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": "fetch_error", "detail": str(exc)}, status_code=502
        )


def _local_asset_search(keyword: str, *, limit: int = 100) -> list[dict[str, Any]]:
    from evolver.gep.paths import get_repo_root

    repo = get_repo_root()
    if repo is None:
        return []

    results: list[dict[str, Any]] = []
    search_dirs = [repo / "assets", repo / "skills", repo / "docs", repo / ".evolver" / "gep"]
    needle = keyword.lower()
    for d in search_dirs:
        if not d.exists():
            continue
        for path in d.rglob("*"):
            if path.is_file() and needle in path.name.lower():
                rel = path.relative_to(repo)
                results.append(
                    {
                        "source": "local",
                        "path": str(rel),
                        "name": path.name,
                        "size": path.stat().st_size,
                    }
                )
            if len(results) >= limit:
                return results
    return results


@router.post("/asset/search")
async def asset_search(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    """Search Hub assets and/or local workspace files by keyword."""
    from evolver.gep import fetch as gep_fetch

    keyword = str(body.get("keyword") or body.get("query") or "").strip()
    if not keyword:
        return JSONResponse({"ok": False, "error": "missing_keyword"}, status_code=400)

    limit = int(body.get("limit", 20))
    local_only = bool(body.get("local", False))
    asset_type = body.get("type")

    if local_only:
        local = _local_asset_search(keyword, limit=limit)
        return JSONResponse({"ok": True, "results": local, "total": len(local), "source": "local"})

    hub_result = await gep_fetch.search_assets(
        keyword, limit=limit, asset_type=str(asset_type) if asset_type else None
    )
    if hub_result.get("ok"):
        assets = hub_result.get("assets", [])
        results = [{"source": "hub", **a} if isinstance(a, dict) else {"source": "hub", "raw": a} for a in assets]
        return JSONResponse(
            {
                "ok": True,
                "results": results,
                "total": len(results),
                "source": "hub",
            }
        )

    local = _local_asset_search(keyword, limit=limit)
    if local:
        return JSONResponse(
            {
                "ok": True,
                "results": local,
                "total": len(local),
                "source": "local_fallback",
                "hub_error": hub_result.get("error"),
            }
        )

    return JSONResponse(
        {
            "ok": False,
            "error": hub_result.get("error", "search_failed"),
            "results": [],
            "total": 0,
        },
        status_code=502 if hub_result.get("error") != "no_hub_url" else 503,
    )


@router.post("/asset/submit")
async def asset_submit(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    result = store.send(
        type="asset_submit",
        payload=body.get("payload", {}),
        ref_id=body.get("ref_id"),
    )
    return JSONResponse(result)


@router.get("/asset/submissions")
async def asset_submissions(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    msgs = store.list(type="asset_submit", direction="outbound", limit=100)
    return JSONResponse({"submissions": [m.to_dict() for m in msgs]})


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.post("/task/subscribe")
async def task_subscribe(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    monitor = _get_task_monitor(request)
    result = monitor.subscribe(filters=body.get("types"))
    return JSONResponse(result)


@router.post("/task/unsubscribe")
async def task_unsubscribe(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    monitor = _get_task_monitor(request)
    return JSONResponse(monitor.unsubscribe())


@router.get("/task/list")
async def task_list(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    claimed = _get_claimed_tasks(request)
    inbox = store.poll(type="task", limit=100)
    tasks: list[dict[str, Any]] = [m.to_dict() for m in inbox]
    for task_id, meta in claimed.items():
        if not any(t.get("task_id") == task_id or t.get("id") == task_id for t in tasks):
            tasks.append(meta)
    return JSONResponse({"tasks": tasks})


@router.post("/task/claim")
async def task_claim(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    task_id = body.get("task_id")
    if not task_id:
        return JSONResponse({"ok": False, "error": "missing_task_id"}, status_code=400)

    monitor = _get_task_monitor(request)
    monitor.record_claim(str(task_id))
    claimed = _get_claimed_tasks(request)
    claimed[str(task_id)] = {
        "task_id": task_id,
        "status": "claimed",
        "claimed_at": time.time(),
        "payload": body.get("payload", {}),
    }
    return JSONResponse({"ok": True, "task_id": task_id})


@router.post("/task/complete")
async def task_complete(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    task_id = body.get("task_id")
    if not task_id:
        return JSONResponse({"ok": False, "error": "missing_task_id"}, status_code=400)

    monitor = _get_task_monitor(request)
    claimed = _get_claimed_tasks(request)
    meta = claimed.get(str(task_id), {})
    started_at = meta.get("claimed_at")
    if body.get("status") == "failed":
        monitor.record_failed(str(task_id))
        if str(task_id) in claimed:
            claimed[str(task_id)]["status"] = "failed"
    else:
        monitor.record_complete(str(task_id), started_at=started_at)
        if str(task_id) in claimed:
            claimed[str(task_id)]["status"] = "completed"
    return JSONResponse({"ok": True, "task_id": task_id})


@router.get("/task/metrics")
async def task_metrics(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    monitor = _get_task_monitor(request)
    return JSONResponse(monitor.get_metrics())


# ---------------------------------------------------------------------------
# DM
# ---------------------------------------------------------------------------


@router.post("/dm/send")
async def dm_send(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    result = store.send(
        type="dm",
        payload=body.get("payload", {}),
        ref_id=body.get("to"),
    )
    return JSONResponse(result)


@router.post("/dm/poll")
async def dm_poll(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    dm_handler = _get_dm_handler(request)
    msgs = store.poll(type="dm", limit=body.get("limit", 100))
    processed: list[dict[str, Any]] = []
    for msg in msgs:
        entry = msg.to_dict()
        if dm_handler is not None:
            entry["dm_result"] = dm_handler.process(entry)
        processed.append(entry)
    return JSONResponse({"messages": processed})


@router.get("/dm/list")
async def dm_list(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    store = _get_store(request)
    msgs = store.poll(type="dm", limit=100)
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@router.post("/session/create")
async def session_create(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    handler = _get_session_handler(request)
    result = handler.create(owner=body.get("owner"), metadata=body.get("metadata"))
    return JSONResponse(result)


@router.post("/session/join")
async def session_join(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    handler = _get_session_handler(request)
    result = handler.join(
        session_id=body.get("session_id", ""),
        participant=body.get("participant", ""),
    )
    return JSONResponse(result)


@router.post("/session/leave")
async def session_leave(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    handler = _get_session_handler(request)
    result = handler.leave(
        session_id=body.get("session_id", ""),
        participant=body.get("participant", ""),
    )
    return JSONResponse(result)


@router.post("/session/message")
async def session_message(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    handler = _get_session_handler(request)
    result = handler.message(
        session_id=body.get("session_id", ""),
        sender=body.get("sender", ""),
        content=body.get("content", ""),
    )
    return JSONResponse(result)


@router.post("/session/delegate")
async def session_delegate(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    handler = _get_session_handler(request)
    result = handler.delegate(
        session_id=body.get("session_id", ""),
        from_participant=body.get("from", ""),
        to_participant=body.get("to", ""),
    )
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Proxy status
# ---------------------------------------------------------------------------


@router.get("/proxy/status")
async def proxy_status(request: Request) -> JSONResponse:
    store = getattr(request.app.state, "mailbox_store", None)
    return JSONResponse(
        {
            "status": "ok",
            "pending_outbound": store.count_pending(direction="outbound") if store else 0,
            "pending_inbound": store.count_pending(direction="inbound") if store else 0,
        }
    )


@router.get("/extensions/skills/updates")
async def extensions_skills_updates(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse(_get_skill_updater(request).check_for_updates())


@router.post("/extensions/skills/process")
async def extensions_skills_process(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    updater = _get_skill_updater(request)
    result = await updater.process_updates()
    return JSONResponse(result)


@router.get("/proxy/hub-status")
async def proxy_hub_status(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    lifecycle = getattr(request.app.state, "lifecycle_manager", None)
    if lifecycle is not None:
        state = getattr(lifecycle, "state", None)
        connected = state is not None and str(state) in ("HEARTBEATING", "AUTHENTICATED")
        return JSONResponse(
            {
                "connected": connected,
                "state": str(state) if state is not None else "unknown",
            }
        )
    store = getattr(request.app.state, "mailbox_store", None)
    pending = store.count_pending(direction="outbound") if store else 0
    return JSONResponse(
        {"connected": False, "pending_outbound": pending, "note": "lifecycle_not_started"}
    )


# ---------------------------------------------------------------------------
# ATP
# ---------------------------------------------------------------------------


@router.post("/atp/order")
async def atp_order(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    from evolver.atp import settlement

    order_id = body.get("order_id") or f"ord_{uuid.uuid4().hex[:12]}"
    budget = float(body.get("budget", 0) or 0)
    if budget > 0:
        debit = settlement.debit(budget, reason=f"order:{order_id}")
        if not debit.get("ok"):
            return JSONResponse(debit, status_code=400)

    orders = _get_atp_orders(request)
    order = {
        "order_id": order_id,
        "status": "pending",
        "service_id": body.get("service_id"),
        "budget": budget,
        "created_at": time.time(),
    }
    orders[order_id] = order
    return JSONResponse({"ok": True, "order_id": order_id, "order": order})


@router.post("/atp/deliver")
async def atp_deliver(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    order_id = body.get("order_id")
    if not order_id:
        return JSONResponse({"ok": False, "error": "missing_order_id"}, status_code=400)
    orders = _get_atp_orders(request)
    order = orders.get(str(order_id))
    if order is None:
        return JSONResponse({"ok": False, "error": "order_not_found"}, status_code=404)
    order["status"] = "delivered"
    order["proof"] = body.get("proof")
    order["delivered_at"] = time.time()
    proofs: list[dict[str, Any]] = getattr(request.app.state, "atp_proofs", [])
    proofs.append({"order_id": order_id, "proof": body.get("proof"), "ts": order["delivered_at"]})
    request.app.state.atp_proofs = proofs
    return JSONResponse({"ok": True, "order_id": order_id, "status": "delivered"})


@router.post("/atp/verify")
async def atp_verify(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    order_id = body.get("order_id")
    orders = _get_atp_orders(request)
    order = orders.get(str(order_id)) if order_id else None
    verdict = body.get("verdict", "passed")
    score = float(body.get("score", 1.0 if verdict == "passed" else 0.0))
    if order is not None:
        order["status"] = "verified" if verdict == "passed" else "failed"
        order["verification_score"] = score
    return JSONResponse({"ok": True, "order_id": order_id, "verdict": verdict, "score": score})


@router.post("/atp/settle")
async def atp_settle(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    from evolver.atp import settlement

    order_id = body.get("order_id")
    if not order_id:
        return JSONResponse({"ok": False, "error": "missing_order_id"}, status_code=400)
    orders = _get_atp_orders(request)
    order = orders.get(str(order_id))
    if order is None:
        return JSONResponse({"ok": False, "error": "order_not_found"}, status_code=404)
    order["status"] = "settled"
    order["settled_at"] = time.time()
    payout = float(body.get("payout", order.get("budget", 0) or 0))
    if payout > 0:
        settlement.credit(payout, reason=f"settle:{order_id}")
    return JSONResponse({"ok": True, "order_id": order_id, "status": "settled"})


@router.post("/atp/dispute")
async def atp_dispute(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    order_id = body.get("order_id")
    orders = _get_atp_orders(request)
    if order_id and str(order_id) in orders:
        orders[str(order_id)]["status"] = "disputed"
        orders[str(order_id)]["dispute_reason"] = body.get("reason", "")
    return JSONResponse({"ok": True, "order_id": order_id, "status": "disputed"})


@router.get("/atp/merchant/tier")
async def atp_merchant_tier(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    from evolver.atp import settlement

    balance = settlement.get_balance().get("balance", 0.0)
    tier = "basic"
    if balance >= 100:
        tier = "premium"
    elif balance >= 10:
        tier = "standard"
    return JSONResponse({"tier": tier, "balance": balance})


@router.get("/atp/order/{order_id}")
async def atp_order_get(
    request: Request,
    order_id: str,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    orders = _get_atp_orders(request)
    order = orders.get(order_id)
    if order is None:
        return JSONResponse({"ok": False, "error": "order_not_found"}, status_code=404)
    return JSONResponse(order)


@router.get("/atp/proofs")
async def atp_proofs(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    proofs: list[dict[str, Any]] = getattr(request.app.state, "atp_proofs", [])
    order_id = request.query_params.get("order_id")
    if order_id:
        proofs = [p for p in proofs if p.get("order_id") == order_id]
    return JSONResponse({"proofs": proofs})


@router.get("/atp/policy")
async def atp_policy(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    from evolver.atp import settlement

    balance = settlement.get_balance()
    return JSONResponse(
        {
            "policy": "default",
            "daily_budget": float(os.environ.get("EVOLVER_ATP_DAILY_BUDGET", "10")),
            "per_order_budget": float(os.environ.get("EVOLVER_ATP_PER_ORDER_BUDGET", "5")),
            "balance": balance.get("balance", 0.0),
        }
    )


# ---------------------------------------------------------------------------
# LLM proxy
# ---------------------------------------------------------------------------


@router.post("/v1/messages", response_model=None)
async def llm_messages(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse | StreamingResponse:
    """Proxy LLM messages to the configured upstream (Anthropic or Bedrock)."""
    return await handle_messages(request=request, body=body)
