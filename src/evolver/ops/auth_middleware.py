"""Lightweight auth middleware for the Evolver WebUI.

Roles: readonly (GET / view only) and admin (full control).
Tokens are persisted to ``~/.evolver/webui_auth.json``.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, WebSocket


def _auth_path() -> Path:
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / "webui_auth.json"


def load_auth_db() -> dict[str, Any]:
    path = _auth_path()
    if not path.exists():
        return {"tokens": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tokens": {}}


def save_auth_db(data: dict[str, Any]) -> None:
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def create_token(role: str = "readonly") -> str:
    """Generate a new random token and persist it."""
    token = secrets.token_urlsafe(32)
    db = load_auth_db()
    db["tokens"][token] = {"role": role}
    save_auth_db(db)
    return token


def revoke_token(token: str) -> bool:
    db = load_auth_db()
    if token in db.get("tokens", {}):
        del db["tokens"][token]
        save_auth_db(db)
        return True
    return False


def _extract_token(request: Request | WebSocket) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def require_role(request: Request, min_role: str = "readonly") -> str:
    """FastAPI dependency that enforces token-based role access.

    Raises 401/403 if the token is missing or insufficient.
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    db = load_auth_db()
    entry = db.get("tokens", {}).get(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid token")

    role = entry.get("role", "readonly")
    hierarchy = {"readonly": 0, "admin": 1}
    if hierarchy.get(role, 0) < hierarchy.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient privileges")

    return token


def ws_require_role(websocket: WebSocket, min_role: str = "readonly") -> str:
    """WebSocket variant of require_role."""
    token = _extract_token(websocket)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    db = load_auth_db()
    entry = db.get("tokens", {}).get(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid token")

    role = entry.get("role", "readonly")
    hierarchy = {"readonly": 0, "admin": 1}
    if hierarchy.get(role, 0) < hierarchy.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient privileges")

    return token
