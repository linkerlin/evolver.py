"""Proxy bearer-token mint / reuse across daemon restarts.

Ports the token lifecycle from Node ``proxy/server/http.js`` + ``settings.js``:

1. Capture prior ``settings.proxy.token`` (and ``previous_tokens``) before wipe.
2. ``clear_if_stale`` removes the proxy block when the previous PID is dead.
3. Prefer prior token → managed Claude client token → mint new 32-byte hex.
4. Persist ``proxy.{url,pid,started_at,token,previous_tokens?}`` and install
   into ``EVOMAP_PROXY_TOKEN`` + optional ``~/.evomap/proxy-token``.
5. Optionally sync Claude client settings (ANTHROPIC_* → local proxy).
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evolver.proxy.client_settings import (
    is_valid_reusable_proxy_token,
    read_reusable_client_proxy_token,
    sync_claude_proxy_settings,
)
from evolver.proxy.server.settings import load_settings, save_settings

logger = logging.getLogger(__name__)


def mint_proxy_token() -> str:
    """Return a fresh 32-byte hex token (64 chars)."""
    return secrets.token_hex(32)


def _proxy_block(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    data = settings if settings is not None else load_settings()
    proxy = data.get("proxy")
    return dict(proxy) if isinstance(proxy, dict) else {}


def _filter_previous_tokens(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and is_valid_reusable_proxy_token(item.strip()):
            out.append(item.strip())
    return out


def is_proxy_pid_stale(pid: Any) -> bool:
    """True when *pid* is set but no longer running (ESRCH)."""
    try:
        n = int(pid)
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    try:
        os.kill(n, 0)
        return False  # process exists
    except ProcessLookupError:
        return True
    except PermissionError:
        # Exists but not ours — treat as live.
        return False
    except OSError:
        return True


def is_stale_proxy(settings: dict[str, Any] | None = None) -> bool:
    """True when settings.proxy.pid points at a dead process."""
    proxy = _proxy_block(settings)
    pid = proxy.get("pid")
    if pid is None:
        return False
    return is_proxy_pid_stale(pid)


def clear_settings_proxy(*, force: bool = False) -> bool:
    """Remove the ``proxy`` block from settings.json.

    Without *force*, refuses to clear when another live PID owns the block.
    """
    data = load_settings()
    proxy = data.get("proxy")
    if not isinstance(proxy, dict):
        return False
    pid = proxy.get("pid")
    if not force and pid is not None:
        try:
            if int(pid) != os.getpid() and not is_proxy_pid_stale(pid):
                return False
        except (TypeError, ValueError):
            pass
    data.pop("proxy", None)
    save_settings(data)
    return True


def clear_if_stale() -> bool:
    """Force-clear proxy settings when the previous owner PID is dead."""
    if is_stale_proxy():
        return clear_settings_proxy(force=True)
    return False


def write_proxy_token_file(token: str, path: Path | None = None) -> Path:
    """Persist token to ``~/.evomap/proxy-token`` (mode 0o600 best-effort)."""
    dest = path or (Path.home() / ".evomap" / "proxy-token")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(token.strip() + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o600)
    return dest


def resolve_proxy_token(
    *,
    port: int,
    host: str = "127.0.0.1",
    sync_client: bool = True,
    client_settings_opts: dict[str, Any] | None = None,
    write_token_file: bool = True,
) -> dict[str, Any]:
    """Resolve (reuse or mint) the proxy bearer token and persist runtime state.

    Returns ``{token, url, port, reused, source, previous_tokens}``.
    """
    prior = _proxy_block()
    previous = (
        prior["token"].strip()
        if isinstance(prior.get("token"), str) and is_valid_reusable_proxy_token(prior["token"])
        else None
    )
    prior_previous = _filter_previous_tokens(prior.get("previous_tokens"))

    # Capture first, then wipe stale owner metadata (token already captured).
    cleared = clear_if_stale()

    opts = dict(client_settings_opts or {})
    opts.setdefault("port", port)
    client_token = read_reusable_client_proxy_token(opts)

    source = "mint"
    if previous:
        token = previous
        source = "settings"
    elif client_token:
        token = client_token
        source = "client_settings"
    else:
        token = mint_proxy_token()
        source = "mint"

    url = f"http://{host}:{port}"
    proxy_block: dict[str, Any] = {
        "url": url,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "token": token,
    }
    if prior_previous:
        proxy_block["previous_tokens"] = prior_previous

    data = load_settings()
    data["proxy"] = proxy_block
    save_settings(data)

    os.environ["EVOMAP_PROXY_TOKEN"] = token
    if write_token_file:
        try:
            write_proxy_token_file(token)
        except OSError as exc:
            logger.debug("[proxy] could not write proxy-token file: %s", exc)

    sync_result: dict[str, Any] | None = None
    if sync_client:
        try:
            sync_result = sync_claude_proxy_settings(
                {
                    **opts,
                    "url": url,
                    "port": port,
                    "token": token,
                    "runtimeEnv": os.environ,
                }
            )
            if sync_result.get("synced") and sync_result.get("changed"):
                logger.info("[proxy] Synced Claude client settings at %s", sync_result.get("file"))
            elif sync_result.get("reason") == "invalid_settings_json":
                logger.warning(
                    "[proxy] Skipped Claude client settings sync (%s)",
                    sync_result.get("file"),
                )
        except Exception as exc:
            logger.warning("[proxy] Claude client settings sync failed: %s", exc)
            sync_result = {"synced": False, "reason": str(exc)}

    return {
        "token": token,
        "url": url,
        "port": port,
        "reused": source != "mint",
        "source": source,
        "previous_tokens": prior_previous,
        "stale_cleared": cleared,
        "client_sync": sync_result,
        "ts": time.time(),
    }


def accepted_proxy_tokens() -> list[str]:
    """Primary token + grace ``previous_tokens`` for auth checks."""
    tokens: list[str] = []
    env = (os.environ.get("EVOMAP_PROXY_TOKEN") or "").strip()
    if is_valid_reusable_proxy_token(env):
        tokens.append(env)
    else:
        # Fall back to token file / settings if env not installed yet.
        proxy = _proxy_block()
        tok = proxy.get("token")
        if isinstance(tok, str) and is_valid_reusable_proxy_token(tok):
            tokens.append(tok.strip())
        token_file = Path.home() / ".evomap" / "proxy-token"
        try:
            if token_file.exists():
                file_tok = token_file.read_text(encoding="utf-8").strip()
                if is_valid_reusable_proxy_token(file_tok):
                    tokens.append(file_tok)
        except OSError:
            pass

    extras = _filter_previous_tokens(_proxy_block().get("previous_tokens"))
    for t in extras:
        if t not in tokens:
            tokens.append(t)
    return tokens


def timing_safe_equal(a: str, b: str) -> bool:
    """Constant-time string compare for bearer tokens."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def authorize_bearer(provided: str) -> bool:
    """True if *provided* matches the primary or any grace previous token."""
    if not provided:
        return False
    candidates = accepted_proxy_tokens()
    if not candidates:
        # No token configured yet — open mode (tests without token install).
        return True
    for cand in candidates:
        if len(provided) == len(cand) and timing_safe_equal(provided, cand):
            return True
    return False


__all__ = [
    "accepted_proxy_tokens",
    "authorize_bearer",
    "clear_if_stale",
    "clear_settings_proxy",
    "is_proxy_pid_stale",
    "is_stale_proxy",
    "mint_proxy_token",
    "resolve_proxy_token",
    "timing_safe_equal",
    "write_proxy_token_file",
]
