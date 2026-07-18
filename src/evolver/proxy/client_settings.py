"""Claude client settings sync for the local proxy.

Equivalent to ``evolver/src/proxy/clientSettings.js`` (G10.6).  Distinct from
:mod:`evolver.proxy.server.settings`, which persists the proxy's own state.
"""

# Direct port of Node fail-fast branch structure.
# ruff: noqa: PLR0912, PLR0915

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MANAGED_BY = "evomap-proxy"
_REUSABLE_PROXY_TOKEN_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
_SYNCED_VARS = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "CUSTOM_API_KEY",
    "EVOMAP_PROXY_URL",
]


def _get_home_dir(env: dict[str, str]) -> str | None:
    home = str(env.get("HOME") or env.get("USERPROFILE") or "").strip()
    if home:
        return home
    try:
        fallback = str(Path.home()).strip()
    except (OSError, RuntimeError):
        return None
    # Path("") normalizes to "." — treat that as "no home directory".
    return fallback if fallback not in ("", ".") else None


def _normalize_settings_path(value: str | None, home: str | None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if home and raw == "~":
        return Path(home).resolve()
    if home and (raw.startswith("~/") or raw.startswith("~\\")):
        return (Path(home) / raw[2:]).resolve()
    return Path(raw).resolve()


def _same_path(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    if sys.platform == "win32":
        return str(left).lower() == str(right).lower()
    return str(left) == str(right)


def _env_claude_settings_file(env: dict[str, str]) -> str:
    return str(
        env.get("CLAUDE_SETTINGS_FILE") or env.get("EVOMAP_CLAUDE_SETTINGS_FILE") or ""
    ).strip()


def is_valid_reusable_proxy_token(value: Any) -> bool:
    return isinstance(value, str) and bool(_REUSABLE_PROXY_TOKEN_RE.match(value.strip()))


def _normalize_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def is_loopback_proxy_url(value: Any) -> bool:
    raw = _normalize_url(value)
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return False
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _safe_upstream_base_url(value: Any, proxy_url: Any) -> str:
    base_url = _normalize_url(value)
    if not base_url or base_url == _normalize_url(proxy_url):
        return ""
    return base_url


def _safe_upstream_token(value: Any, proxy_token: str) -> str:
    token = value.strip() if isinstance(value, str) else ""
    if not token or token == proxy_token:
        return ""
    return token


def get_claude_settings_file(env: dict[str, str] | None = None) -> Path | None:
    environment = dict(os.environ) if env is None else env
    home = _get_home_dir(environment)
    if not home:
        return None
    return Path(home) / ".claude" / "settings.json"


def _resolve_claude_settings_file(
    opts: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    if opts.get("file"):
        return {"file": Path(opts["file"]), "source": "opts"}

    default_file = get_claude_settings_file(env)
    if default_file is None:
        return {"file": None, "reason": "missing_settings_path"}

    env_file = _env_claude_settings_file(env)
    if not env_file:
        return {"file": default_file, "source": "default"}

    home = _get_home_dir(env)
    if _same_path(
        _normalize_settings_path(env_file, home),
        _normalize_settings_path(str(default_file), home),
    ):
        return {"file": default_file, "source": "env_default"}
    return {"file": None, "reason": "unsafe_settings_path"}


def _read_json_file_result(file: Path | None) -> dict[str, Any]:
    try:
        if file is None or not file.exists():
            return {"exists": False, "ok": True, "value": None}
        return {
            "exists": True,
            "ok": True,
            "value": json.loads(file.read_text(encoding="utf-8")),
        }
    except (OSError, json.JSONDecodeError):
        return {"exists": file is not None, "ok": False, "value": None}


def _write_private_json_file(file: Path, data: dict[str, Any]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):  # best-effort on Windows
        os.chmod(file, 0o600)


def _is_disabled(env: dict[str, str]) -> bool:
    raw = str(env.get("EVOMAP_PROXY_AUTO_INJECT") or "").strip().lower()
    return raw in ("0", "false", "off", "none", "no")


def _has_managed_proxy_marker(settings: Any) -> bool:
    if not isinstance(settings, dict):
        return False
    marker = settings.get("_evomap_proxy_client_env")
    return isinstance(marker, dict) and marker.get("managed_by") == MANAGED_BY


def _is_managed_proxy_base_url(
    settings: Any,
    cfg: dict[str, Any],
    value: Any,
    proxy_url: Any,
) -> bool:
    base_url = _normalize_url(value)
    if not is_loopback_proxy_url(base_url):
        return False
    if base_url == _normalize_url(proxy_url):
        return True
    if _has_managed_proxy_marker(settings):
        return True
    if str(cfg.get("EVOMAP_PROXY_AUTO_INJECTED") or "") == "1":
        return True
    marked_proxy_url = _normalize_url(cfg.get("EVOMAP_PROXY_URL"))
    return bool(
        marked_proxy_url
        and is_loopback_proxy_url(marked_proxy_url)
        and marked_proxy_url == base_url
    )


def _is_managed_proxy_upstream_residual(
    settings: Any,
    cfg: dict[str, Any],
    base_value: Any,
    token_value: Any,
    api_key_value: Any,
) -> bool:
    base_url = _normalize_url(base_value)
    token = token_value.strip() if isinstance(token_value, str) else ""
    api_key = api_key_value.strip() if isinstance(api_key_value, str) else ""
    if not is_loopback_proxy_url(base_url) or (
        not is_valid_reusable_proxy_token(token) and not is_valid_reusable_proxy_token(api_key)
    ):
        return False
    return (
        _has_managed_proxy_marker(settings)
        or str(cfg.get("EVOMAP_PROXY_AUTO_INJECTED") or "") == "1"
    )


def _safe_stored_upstream_base_url(
    settings: Any,
    cfg: dict[str, Any],
    value: Any,
    proxy_url: Any,
) -> str:
    base_url = _normalize_url(value)
    if not base_url or base_url == _normalize_url(proxy_url):
        return ""
    marked_proxy_url = _normalize_url(cfg.get("EVOMAP_PROXY_URL"))
    if marked_proxy_url and base_url == marked_proxy_url:
        return ""
    anthropic_base = cfg.get("ANTHROPIC_BASE_URL")
    if base_url == _normalize_url(anthropic_base) and _is_managed_proxy_base_url(
        settings, cfg, anthropic_base, proxy_url
    ):
        return ""
    return _safe_upstream_base_url(value, proxy_url)


def read_reusable_client_proxy_token(opts: dict[str, Any] | None = None) -> str | None:
    """Recover the previous daemon's proxy token from managed client settings."""
    options = opts or {}
    env = options.get("env") or dict(os.environ)
    if _is_disabled(env):
        return None

    resolved = _resolve_claude_settings_file(options, env)
    file = resolved.get("file")
    if file is None:
        return None
    result = _read_json_file_result(file)
    settings = result["value"] if result["ok"] else None
    cfg = settings.get("env") if isinstance(settings, dict) else None
    if not isinstance(cfg, dict):
        return None

    base_url = _normalize_url(cfg.get("ANTHROPIC_BASE_URL"))
    raw_token = cfg.get("ANTHROPIC_AUTH_TOKEN")
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if (
        not is_valid_reusable_proxy_token(token)
        or not _is_managed_proxy_base_url(
            settings, cfg, cfg.get("ANTHROPIC_BASE_URL"), options.get("url")
        )
        or not is_loopback_proxy_url(base_url)
    ):
        return None
    return token


def _backup_existing_file(file: Path) -> Path | None:
    try:
        if not file.exists():
            return None
        stamp = (
            datetime.now(UTC).isoformat().replace("+00:00", "Z").replace("-", "").replace(":", "")
        )
        stamp = re.sub(r"\.\d+Z$", "Z", stamp)
        backup_dir = file.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for index in range(10):
            suffix = "" if index == 0 else f"-{index}"
            backup_file = backup_dir / f"settings.json.pre-evomap-proxy-sync-{stamp}{suffix}"
            if backup_file.exists():
                continue
            backup_file.write_bytes(file.read_bytes())
            with contextlib.suppress(OSError):
                os.chmod(backup_file, 0o600)
            return backup_file
        return None
    except OSError:
        return None


def sync_claude_proxy_settings(info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Point Claude client settings at the active proxy, preserving upstream."""
    options = info or {}
    env = options.get("env") or dict(os.environ)
    if _is_disabled(env):
        return {"synced": False, "reason": "disabled"}

    url = _normalize_url(options.get("url"))
    raw_token = options.get("token")
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if not url or not is_valid_reusable_proxy_token(token):
        return {"synced": False, "reason": "missing_proxy_settings"}

    resolved = _resolve_claude_settings_file(options, env)
    file = resolved.get("file")
    if file is None:
        return {
            "synced": False,
            "changed": False,
            "reason": resolved.get("reason") or "missing_settings_path",
        }

    current_result = _read_json_file_result(file)
    if current_result["exists"] and not current_result["ok"]:
        backup_file = None if options.get("backup") is False else _backup_existing_file(file)
        return {
            "synced": False,
            "changed": False,
            "reason": "invalid_settings_json",
            "file": file,
            "backupFile": backup_file,
        }
    current = current_result["value"]
    settings: dict[str, Any] = current if isinstance(current, dict) else {}
    raw_cfg = settings.get("env")
    cfg: dict[str, Any] = dict(raw_cfg) if isinstance(raw_cfg, dict) else {}

    existing_base = _normalize_url(cfg.get("ANTHROPIC_BASE_URL"))
    existing_token = (
        cfg["ANTHROPIC_AUTH_TOKEN"].strip()
        if isinstance(cfg.get("ANTHROPIC_AUTH_TOKEN"), str)
        else ""
    )
    existing_api_key = (
        cfg["ANTHROPIC_API_KEY"].strip() if isinstance(cfg.get("ANTHROPIC_API_KEY"), str) else ""
    )
    existing_base_is_proxy = _is_managed_proxy_base_url(
        settings, cfg, existing_base, options.get("url")
    )
    runtime_env = options.get("runtime_env")
    runtime_env = runtime_env if isinstance(runtime_env, dict) else None

    changed = False
    runtime_changed = False
    runtime_upstream_changed = False

    def set_if_changed(key: str, value: Any) -> None:
        nonlocal changed
        if cfg.get(key) == value:
            return
        cfg[key] = value
        changed = True

    def delete_if_present(key: str) -> None:
        nonlocal changed
        if key not in cfg:
            return
        del cfg[key]
        changed = True

    def set_runtime_if_missing(key: str, value: str) -> bool:
        nonlocal runtime_changed, runtime_upstream_changed
        if runtime_env is None or not value:
            return False
        if str(runtime_env.get(key) or "").strip():
            return False
        runtime_env[key] = value
        runtime_changed = True
        runtime_upstream_changed = True
        return True

    if _is_managed_proxy_upstream_residual(
        settings,
        cfg,
        cfg.get("EVOMAP_ANTHROPIC_BASE_URL"),
        cfg.get("EVOMAP_ANTHROPIC_AUTH_TOKEN"),
        cfg.get("EVOMAP_ANTHROPIC_API_KEY"),
    ):
        delete_if_present("EVOMAP_ANTHROPIC_BASE_URL")
        delete_if_present("EVOMAP_ANTHROPIC_AUTH_TOKEN")
        delete_if_present("EVOMAP_ANTHROPIC_API_KEY")

    migrated_base_url = (
        "" if existing_base_is_proxy else _safe_upstream_base_url(existing_base, options.get("url"))
    )
    if migrated_base_url and not cfg.get("EVOMAP_ANTHROPIC_BASE_URL"):
        set_if_changed("EVOMAP_ANTHROPIC_BASE_URL", migrated_base_url)
    migrated_auth_token = (
        "" if existing_base_is_proxy else _safe_upstream_token(existing_token, token)
    )
    if migrated_auth_token and not cfg.get("EVOMAP_ANTHROPIC_AUTH_TOKEN"):
        set_if_changed("EVOMAP_ANTHROPIC_AUTH_TOKEN", migrated_auth_token)
    if (
        existing_api_key
        and existing_api_key not in (token, existing_token)
        and not cfg.get("EVOMAP_ANTHROPIC_API_KEY")
    ):
        set_if_changed("EVOMAP_ANTHROPIC_API_KEY", existing_api_key)

    runtime_had_upstream_base = bool(
        runtime_env is not None and str(runtime_env.get("EVOMAP_ANTHROPIC_BASE_URL") or "").strip()
    )
    runtime_base_synced = set_runtime_if_missing(
        "EVOMAP_ANTHROPIC_BASE_URL",
        _safe_stored_upstream_base_url(
            settings, cfg, cfg.get("EVOMAP_ANTHROPIC_BASE_URL"), options.get("url")
        ),
    )
    if not runtime_had_upstream_base or runtime_base_synced:
        upstream_auth_token = _safe_upstream_token(cfg.get("EVOMAP_ANTHROPIC_AUTH_TOKEN"), token)
        if not (existing_base_is_proxy and upstream_auth_token == existing_token):
            set_runtime_if_missing("EVOMAP_ANTHROPIC_AUTH_TOKEN", upstream_auth_token)
        upstream_api_key = _safe_upstream_token(cfg.get("EVOMAP_ANTHROPIC_API_KEY"), token)
        if upstream_api_key and upstream_api_key != existing_token:
            set_runtime_if_missing("EVOMAP_ANTHROPIC_API_KEY", upstream_api_key)
    if (
        runtime_env is not None
        and runtime_upstream_changed
        and runtime_env.get("EVOMAP_PROXY_AUTO_INJECTED") != "1"
    ):
        runtime_env["EVOMAP_PROXY_AUTO_INJECTED"] = "1"
        runtime_changed = True

    set_if_changed("ANTHROPIC_BASE_URL", url)
    set_if_changed("ANTHROPIC_AUTH_TOKEN", token)
    delete_if_present("ANTHROPIC_API_KEY")
    set_if_changed("CUSTOM_API_KEY", token)
    set_if_changed("EVOMAP_PROXY_URL", url)
    set_if_changed("EVOMAP_PROXY_AUTO_INJECTED", "1")

    if not _has_managed_proxy_marker(settings):
        settings["_evomap_proxy_client_env"] = {"managed_by": MANAGED_BY}
        changed = True

    if not changed:
        return {
            "synced": True,
            "changed": False,
            "runtimeChanged": runtime_changed,
            "file": file,
            "vars": list(_SYNCED_VARS),
        }

    settings["env"] = cfg
    settings["_evomap_proxy_client_env"] = {
        "managed_by": MANAGED_BY,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    backup_file = None if options.get("backup") is False else _backup_existing_file(file)
    _write_private_json_file(file, settings)

    return {
        "synced": True,
        "changed": True,
        "runtimeChanged": runtime_changed,
        "file": file,
        "backupFile": backup_file,
        "vars": list(_SYNCED_VARS),
    }


__all__ = [
    "MANAGED_BY",
    "get_claude_settings_file",
    "is_loopback_proxy_url",
    "is_valid_reusable_proxy_token",
    "read_reusable_client_proxy_token",
    "sync_claude_proxy_settings",
]
