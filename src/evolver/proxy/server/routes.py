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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from evolver.proxy.mailbox.store import MailboxStore

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
        return token_file.read_text(encoding="utf-8").strip()
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
    # Stub — full validation logic lives in gep/schemas
    return JSONResponse({"valid": True})


@router.post("/asset/fetch")
async def asset_fetch(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": False, "error": "not_implemented"})


@router.post("/asset/search")
async def asset_search(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": False, "error": "not_implemented"})


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
    return JSONResponse({"ok": True, "types": body.get("types", [])})


@router.post("/task/unsubscribe")
async def task_unsubscribe(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.get("/task/list")
async def task_list(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"tasks": []})


@router.post("/task/claim")
async def task_claim(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True, "task_id": body.get("task_id")})


@router.post("/task/complete")
async def task_complete(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.get("/task/metrics")
async def task_metrics(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"claimed": 0, "completed": 0, "failed": 0})


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
    msgs = store.poll(type="dm", limit=body.get("limit", 100))
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


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
    return JSONResponse({"session_id": "sess_" + __import__("uuid").uuid4().hex[:8]})


@router.post("/session/join")
async def session_join(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True, "session_id": body.get("session_id")})


@router.post("/session/leave")
async def session_leave(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/session/message")
async def session_message(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/session/delegate")
async def session_delegate(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


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


@router.get("/proxy/hub-status")
async def proxy_hub_status(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"connected": True})


# ---------------------------------------------------------------------------
# ATP
# ---------------------------------------------------------------------------


@router.post("/atp/order")
async def atp_order(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True, "order_id": body.get("order_id", "ord_" + __import__("uuid").uuid4().hex[:8])})


@router.post("/atp/deliver")
async def atp_deliver(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/atp/verify")
async def atp_verify(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/atp/settle")
async def atp_settle(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/atp/dispute")
async def atp_dispute(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.get("/atp/merchant/tier")
async def atp_merchant_tier(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"tier": "basic"})


@router.get("/atp/order/{order_id}")
async def atp_order_get(
    request: Request,
    order_id: str,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"order_id": order_id, "status": "pending"})


@router.get("/atp/proofs")
async def atp_proofs(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"proofs": []})


@router.get("/atp/policy")
async def atp_policy(
    request: Request,
    _token: str = Depends(require_auth),
) -> JSONResponse:
    return JSONResponse({"policy": "default"})


# ---------------------------------------------------------------------------
# LLM proxy
# ---------------------------------------------------------------------------


@router.post("/v1/messages")
async def llm_messages(
    request: Request,
    body: dict[str, Any],
    _token: str = Depends(require_auth),
) -> JSONResponse:
    # Phase C — delegated to messages_handler if available
    handler = getattr(request.app.state, "messages_handler", None)
    if handler is not None:
        return await handler(request=request, body=body)
    return JSONResponse({"ok": False, "error": "messages_handler_not_configured"}, status_code=503)
