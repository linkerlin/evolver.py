"""Canonical node identity helpers (node_id file + state-path suffix).

Behaviour mirrors Node ``a2aProtocol`` / ``lifecycle/manager`` identity
unification (v1.92.0):

* ``NODE_ID_RE`` accepts hub-issued 12-32 hex ids
* legacy ``~/.evomap/node_id`` is the shared identity surface for proxy + A2A
* state-file suffix is first 8 lowercase hex chars, else ``anon`` (no path escape)
* identity transitions clear sibling credential files under the identity lock
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
from pathlib import Path

from evolver.gep.paths import get_evolver_home, get_repo_root

logger = logging.getLogger(__name__)

NODE_ID_RE = re.compile(r"^node_[a-f0-9]{12,32}$")
_HEX8_RE = re.compile(r"^[a-f0-9]{8}$")
_CANONICAL_CREDENTIAL_SIBLINGS = (
    "node_secret",
    "node_secret_version",
    "node_secret_source",
    "node_secret_env_suppressed",
)

# Module-level cache (proxy never calls getNodeId; lifecycle seeds via persist).
_cache: dict[str, str | None] = {"node_id": None}


def is_valid_node_id(node_id: str | None) -> bool:
    return bool(node_id and isinstance(node_id, str) and NODE_ID_RE.match(node_id))


def mint_node_id() -> str:
    """Mint a fresh local node id (12 hex), never derived from device fingerprint."""
    return f"node_{secrets.token_hex(6)}"


def legacy_node_id_path() -> Path:
    return get_evolver_home() / "node_id"


def project_local_node_id_path() -> Path | None:
    repo = get_repo_root(_quiet=True)
    if repo is None:
        return None
    return repo / ".evomap_node_id"


def read_valid_node_id_file(path: Path | str) -> str | None:
    try:
        p = Path(path)
        if not p.is_file():
            return None
        raw = p.read_text(encoding="utf-8").strip()
        return raw if is_valid_node_id(raw) else None
    except OSError:
        return None


def read_legacy_node_id() -> str | None:
    """Read the first valid id from home node_id then project-local fallback."""
    home_id = read_valid_node_id_file(legacy_node_id_path())
    if home_id:
        return home_id
    local = project_local_node_id_path()
    if local is not None:
        return read_valid_node_id_file(local)
    return None


def set_cached_node_id(node_id: str | None) -> None:
    _cache["node_id"] = node_id if is_valid_node_id(node_id) else None


def reset_cached_node_id() -> None:
    _cache["node_id"] = None


def short_node_id_for_state_path(node_id: str | None = None) -> str:
    """Return 8-hex state-file suffix or ``anon`` (path-traversal safe)."""
    candidate = node_id if is_valid_node_id(node_id) else None
    cached = _cache.get("node_id")
    if candidate is None and is_valid_node_id(cached):
        candidate = cached
    if candidate is None:
        candidate = read_legacy_node_id()
    if not candidate:
        return "anon"
    hex_part = candidate.removeprefix("node_")[:8]
    if not _HEX8_RE.match(hex_part):
        return "anon"
    return hex_part


def force_update_last_state_path(node_id: str | None = None) -> Path:
    suffix = short_node_id_for_state_path(node_id)
    return get_evolver_home() / f"force_update_last.{suffix}.json"


def _clear_canonical_credentials(node_id_file: Path) -> bool:
    directory = node_id_file.parent
    cleared = True
    for name in _CANONICAL_CREDENTIAL_SIBLINGS:
        path = directory / name
        try:
            if path.exists():
                path.unlink()
        except OSError:
            cleared = False
        if path.exists():
            cleared = False
    return cleared


def _write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        tmp.replace(path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)


def persist_legacy_node_id(node_id: str | None) -> None:  # noqa: PLR0912
    """Write *node_id* to the shared legacy file (NODE_ID_RE gated).

    On canonical id transition (existing different valid id, or orphan
    credentials), clear sibling credential files under the identity lock
    before publishing the new id — never leave node A credentials bound
    to node B.
    """
    if not is_valid_node_id(node_id):
        return
    assert node_id is not None

    canonical = legacy_node_id_path()
    targets: list[Path] = [canonical]
    local = project_local_node_id_path()
    if local is not None:
        targets.append(local)

    for file in targets:
        release = None
        try:
            if file == canonical:
                from evolver.gep.canonical_identity_lock import (  # noqa: PLC0415
                    acquire_canonical_identity_lock,
                )

                try:
                    release = acquire_canonical_identity_lock(file)
                except Exception:
                    # Never fall through to install-local while another process
                    # may be mutating the canonical tuple.
                    return

            existing = read_valid_node_id_file(file)
            if existing == node_id:
                set_cached_node_id(node_id)
                return

            try:
                file.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    os.chmod(file.parent, 0o700)
            except OSError:
                continue

            is_canonical_transition = file == canonical and existing != node_id
            if is_canonical_transition:
                # Clear A credentials before publishing B (store-wins path).
                has_siblings = any(
                    (file.parent / name).exists() for name in _CANONICAL_CREDENTIAL_SIBLINGS
                )
                if (existing or has_siblings) and not _clear_canonical_credentials(file):
                    logger.warning(
                        "[node_identity] failed to clear credentials before id transition"
                    )
                    return

            _write_private_file(file, node_id)
            set_cached_node_id(node_id)
            return
        except OSError as exc:
            logger.debug("[node_identity] persist failed for %s: %s", file, exc)
            continue
        finally:
            if release is not None:
                try:
                    release()
                except Exception as exc:
                    logger.debug("[node_identity] release lock failed: %s", exc)


def resolve_node_id(
    *,
    store_id: str | None = None,
    allow_mint: bool = True,
) -> str | None:
    """Resolve active node id: store → env → legacy → mint (optional)."""
    if is_valid_node_id(store_id):
        return store_id
    env_id = (os.environ.get("A2A_NODE_ID") or "").strip()
    if env_id:
        if not is_valid_node_id(env_id):
            logger.warning("[node_identity] A2A_NODE_ID has unexpected format: %r", env_id)
        return env_id  # env is used even when malformed (Node warn-but-use)
    legacy = read_legacy_node_id()
    if legacy:
        return legacy
    if allow_mint:
        return mint_node_id()
    return None


__all__ = [
    "NODE_ID_RE",
    "force_update_last_state_path",
    "is_valid_node_id",
    "legacy_node_id_path",
    "mint_node_id",
    "persist_legacy_node_id",
    "project_local_node_id_path",
    "read_legacy_node_id",
    "read_valid_node_id_file",
    "reset_cached_node_id",
    "resolve_node_id",
    "set_cached_node_id",
    "short_node_id_for_state_path",
]
