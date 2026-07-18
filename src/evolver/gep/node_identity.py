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
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Full getNodeId chain (nodeIdResolution) + identity tuples (sync)
# ---------------------------------------------------------------------------

_NODE_SECRET_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)


class NodeIdPersistError(OSError):
    """Raised when a canonical node_id claim cannot be completed safely."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def mailbox_state_path() -> Path:
    return get_evolver_home() / "mailbox" / "state.json"


def load_mailbox_state() -> dict[str, Any] | None:
    path = mailbox_state_path()
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _is_valid_node_secret(secret: str | None) -> bool:
    return bool(secret and isinstance(secret, str) and _NODE_SECRET_RE.match(secret.strip()))


def _parse_secret_version(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _normalize_secret_source(value: Any) -> str | None:
    source = str(value or "").strip()
    return source if source in ("hub_rotate", "env_seed") else None


def read_persisted_secret_tuple() -> dict[str, Any]:
    """Read ``node_secret`` / version / source from EVOLVER_HOME (not mailbox)."""
    home = get_evolver_home()
    secret: str | None = None
    try:
        secret_path = home / "node_secret"
        if secret_path.is_file():
            raw = secret_path.read_text(encoding="utf-8").strip()
            if _is_valid_node_secret(raw):
                secret = raw
    except OSError:
        secret = None
    version: int | None = None
    try:
        ver_path = home / "node_secret_version"
        if ver_path.is_file():
            version = _parse_secret_version(ver_path.read_text(encoding="utf-8").strip())
    except OSError:
        version = None
    source: str | None = None
    try:
        src_path = home / "node_secret_source"
        if src_path.is_file():
            source = _normalize_secret_source(src_path.read_text(encoding="utf-8").strip())
    except OSError:
        source = None
    return {"secret": secret, "version": version, "source": source, "store": "persisted"}


def read_mailbox_identity() -> dict[str, Any]:
    """Read mailbox ``state.json`` identity fields (node_id + secret tuple)."""
    state = load_mailbox_state() or {}
    node_id = state.get("node_id")
    node_id_s = str(node_id).strip() if node_id is not None else ""
    secret_raw = state.get("node_secret")
    secret = str(secret_raw).strip() if isinstance(secret_raw, str) else None
    return {
        "node_id": node_id_s if is_valid_node_id(node_id_s) else None,
        "secret": secret if _is_valid_node_secret(secret) else None,
        "version": _parse_secret_version(state.get("node_secret_version")),
        "source": _normalize_secret_source(state.get("node_secret_source")),
        "store": "mailbox",
        "raw_state": state,
    }


def _prefer_secret_tuple(
    a: dict[str, Any] | None, b: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Prefer higher hub_rotate version; mailbox wins ties (Node parity)."""
    if not a:
        return b
    if not b:
        return a
    a_ver = int(a.get("version") or 0)
    b_ver = int(b.get("version") or 0)
    if a_ver != b_ver:
        return a if a_ver > b_ver else b
    return a if a.get("store") == "mailbox" else b


def _hub_rotate_tuple(
    secret: str | None, version: int | None, source: str | None, store: str
) -> dict[str, Any] | None:
    if not _is_valid_node_secret(secret) or source != "hub_rotate":
        return None
    return {
        "secret": secret,
        "version": version,
        "source": source,
        "store": store,
    }


def _claim_node_id_exclusive(node_id: str) -> str:  # noqa: PLR0915
    """Claim *node_id* under the identity lock; adopt on-disk winner on race."""
    from evolver.gep.canonical_identity_lock import (  # noqa: PLC0415
        CanonicalIdentityLockError,
        acquire_canonical_identity_lock,
    )

    path = legacy_node_id_path()
    try:
        release = acquire_canonical_identity_lock(path)
    except CanonicalIdentityLockError as exc:
        raise NodeIdPersistError(str(exc), code=exc.code) from exc
    except Exception as exc:
        raise NodeIdPersistError(
            f"failed to acquire identity lock: {exc}",
            code="CANONICAL_IDENTITY_LOCK_TIMEOUT",
        ) from exc

    try:
        existing = read_valid_node_id_file(path)
        if existing:
            set_cached_node_id(existing)
            return existing

        # Clear orphan credentials (no node_id but secret files present).
        has_orphans = any((path.parent / name).exists() for name in _CANONICAL_CREDENTIAL_SIBLINGS)
        if has_orphans and not _clear_canonical_credentials(path):
            # Quarantine: write invalid marker and fail closed.
            with contextlib.suppress(OSError):
                _write_private_file(path, "invalid")
            raise NodeIdPersistError(
                "failed to clear orphan credentials before node_id claim",
                code="NODE_ID_PERSIST_FAILED",
            )

        # Clear ownerless mailbox secret tuple before publishing a fresh id.
        _bind_or_clear_mailbox_for_new_identity(node_id)

        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(path.parent, 0o700)

        # Exclusive create (wx). On EEXIST, adopt the winner.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, node_id.encode("utf-8"))
                with contextlib.suppress(OSError):
                    os.fsync(fd)
            finally:
                os.close(fd)
            set_cached_node_id(node_id)
            return node_id
        except FileExistsError:
            winner = read_valid_node_id_file(path)
            if winner:
                set_cached_node_id(winner)
                return winner
            # Malformed occupant — repair under lock.
            _write_private_file(path, node_id)
            set_cached_node_id(node_id)
            return node_id
        except OSError as exc:
            # Windows may surface different codes for exclusive create races.
            winner = read_valid_node_id_file(path)
            if winner:
                set_cached_node_id(winner)
                return winner
            raise NodeIdPersistError(
                f"failed to persist node_id: {exc}",
                code="NODE_ID_PERSIST_FAILED",
            ) from exc
    finally:
        try:
            release()
        except Exception as exc:
            logger.debug("[node_identity] release after claim failed: %s", exc)


def _bind_or_clear_mailbox_for_new_identity(node_id: str) -> None:
    """Clear ownerless mailbox secrets and bind mailbox node_id to *node_id*."""
    path = mailbox_state_path()
    state = load_mailbox_state()
    if state is None:
        return
    # Ownerless or mismatched mailbox secrets must not attach to a new id.
    mb_id = state.get("node_id")
    mb_id_s = str(mb_id).strip() if mb_id is not None else ""
    if is_valid_node_id(mb_id_s) and mb_id_s != node_id:
        # Different node — leave mailbox alone (identity isolation).
        return
    state = dict(state)
    state["node_id"] = node_id
    # Clear secrets when publishing a brand-new identity.
    state["node_secret"] = ""
    state["node_secret_version"] = ""
    state["node_secret_source"] = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("[node_identity] mailbox bind failed: %s", exc)


def get_or_create_node_id() -> str:
    """Full Node ``getNodeId()`` chain with mint + exclusive persist.

    Order: cache → env (warn if malformed) → persisted/project-local →
    valid mailbox (promoted) → random 12-hex under identity lock.
    """
    cached = _cache.get("node_id")
    if isinstance(cached, str) and cached:
        # Cache may hold env-malformed ids (warn-but-use); return as-is.
        return cached

    env_id = (os.environ.get("A2A_NODE_ID") or "").strip()
    if env_id:
        if not is_valid_node_id(env_id):
            logger.warning(
                "[a2aProtocol] A2A_NODE_ID=%s has an unexpected format "
                "(expected node_<12-32 hex chars>). Using it as-is, but hub may reject it.",
                env_id,
            )
            _cache["node_id"] = env_id
            return env_id
        set_cached_node_id(env_id)
        return env_id

    persisted = read_legacy_node_id()
    if persisted:
        set_cached_node_id(persisted)
        return persisted

    # Malformed persisted file: fall through to claim (repair under lock).
    path = legacy_node_id_path()
    try:
        if path.is_file():
            raw = path.read_text(encoding="utf-8").strip()
            if raw and not is_valid_node_id(raw):
                logger.warning("[node_identity] rejecting malformed persisted node_id; will repair")
    except OSError:
        pass

    mailbox = read_mailbox_identity()
    mailbox_id = mailbox.get("node_id")
    if isinstance(mailbox_id, str) and is_valid_node_id(mailbox_id):
        claimed = _claim_node_id_exclusive(mailbox_id)
        return claimed

    logger.warning(
        "[a2aProtocol] A2A_NODE_ID is not set. Generating a fresh node ID. "
        "The ID is persisted locally, so it stays stable across runs on this install."
    )
    return _claim_node_id_exclusive(mint_node_id())


def resolve_readonly_node_id() -> str | None:
    """Resolve node id without minting or writing (sync --dry-run safe)."""
    cached = _cache.get("node_id")
    if isinstance(cached, str) and cached:
        return cached
    env_id = (os.environ.get("A2A_NODE_ID") or "").strip()
    if env_id:
        return env_id
    return read_legacy_node_id()


def resolve_identity_tuple(*, create: bool = True) -> dict[str, Any]:
    """Resolve ``{node_id, secret, version}`` without cross-node credential bleed.

    When mailbox and persisted files belong to **different** node ids, only the
    active node_id's credentials are used (identityTupleSync isolation).
    When both belong to the same node and are hub_rotate, the higher
    ``node_secret_version`` wins (mailbox preferred on ties).
    """
    node_id = get_or_create_node_id() if create else resolve_readonly_node_id()

    env_secret = (
        os.environ.get("A2A_NODE_SECRET") or os.environ.get("EVOMAP_NODE_SECRET") or ""
    ).strip() or None
    env_version = _parse_secret_version(
        os.environ.get("A2A_NODE_SECRET_VERSION") or os.environ.get("EVOMAP_NODE_SECRET_VERSION")
    )

    persisted = read_persisted_secret_tuple()
    mailbox = read_mailbox_identity()

    # Isolate: only accept mailbox credentials when mailbox node matches active.
    mailbox_tuple: dict[str, Any] | None = None
    if node_id and mailbox.get("node_id") == node_id:
        mailbox_tuple = _hub_rotate_tuple(
            mailbox.get("secret"),  # type: ignore[arg-type]
            mailbox.get("version"),  # type: ignore[arg-type]
            mailbox.get("source"),  # type: ignore[arg-type]
            "mailbox",
        )
    elif node_id is None and mailbox.get("node_id"):
        # No active id yet — do not pull foreign mailbox credentials.
        mailbox_tuple = None

    persisted_tuple = _hub_rotate_tuple(
        persisted.get("secret"),  # type: ignore[arg-type]
        persisted.get("version"),  # type: ignore[arg-type]
        persisted.get("source"),  # type: ignore[arg-type]
        "persisted",
    )

    selected = _prefer_secret_tuple(mailbox_tuple, persisted_tuple)

    secret: str | None = None
    version: int | None = None

    if selected:
        secret = str(selected["secret"])
        version = selected.get("version")  # type: ignore[assignment]
    elif env_secret and _is_valid_node_secret(env_secret):
        secret = env_secret
        version = env_version
    elif persisted.get("secret"):
        secret = str(persisted["secret"])
        version = persisted.get("version")  # type: ignore[assignment]
    elif mailbox.get("secret") and (node_id is None or mailbox.get("node_id") == node_id):
        secret = str(mailbox["secret"])
        version = mailbox.get("version")  # type: ignore[assignment]

    return {
        "node_id": node_id,
        "secret": secret,
        "version": version,
    }


def build_identity_hub_headers(*, create: bool = True) -> dict[str, str]:
    """Node-scoped Hub headers derived from :func:`resolve_identity_tuple`."""
    identity = resolve_identity_tuple(create=create)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = identity.get("secret")
    if isinstance(secret, str) and secret:
        headers["Authorization"] = f"Bearer {secret}"
    version = identity.get("version")
    if version is not None:
        headers["X-EvoMap-Node-Secret-Version"] = str(version)
    return headers


__all__ = [
    "NODE_ID_RE",
    "NodeIdPersistError",
    "build_identity_hub_headers",
    "force_update_last_state_path",
    "get_or_create_node_id",
    "is_valid_node_id",
    "legacy_node_id_path",
    "load_mailbox_state",
    "mailbox_state_path",
    "mint_node_id",
    "persist_legacy_node_id",
    "project_local_node_id_path",
    "read_legacy_node_id",
    "read_mailbox_identity",
    "read_persisted_secret_tuple",
    "read_valid_node_id_file",
    "reset_cached_node_id",
    "resolve_identity_tuple",
    "resolve_node_id",
    "resolve_readonly_node_id",
    "set_cached_node_id",
    "short_node_id_for_state_path",
]
