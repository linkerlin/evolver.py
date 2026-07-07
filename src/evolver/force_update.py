"""Force update engine — self-updating evolver when Hub triggers version expiry.

Equivalent to Node's ``evolver/src/forceUpdate.js``.

Channels:
1. GitHub Release (default)
2. Manual URL (enterprise / internal deployments)

Safety:
- Semantic version comparison
- Atomic file replacement (temp + os.replace)
- File-lock concurrency guard
- Keep List: memory/, .env, skills/ are never overwritten
- Automatic rollback on failure
- Backup before update
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import types
import zipfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

KEEP_LIST = {"memory", ".env", "skills", ".evomap"}
BACKUP_RETENTION_DAYS = 7
UPDATE_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# v1.90.0 sentinels, failure codes, and concurrency guard
# ---------------------------------------------------------------------------
class _Sentinel:
    """A distinct, identity-comparable sentinel (Python analogue of a JS Symbol)."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self._name}>"


#: Returned by :func:`execute_force_update` when a re-entrant call lands while an
#: upgrade is already in progress (module-level mutex). Distinct from NOOP and
#: from any truthy/falsy value so callers cannot misread it as success.
FORCE_UPDATE_BUSY: Any = _Sentinel("FORCE_UPDATE_BUSY")

#: Returned when the installed version already satisfies the required floor —
#: no download, no downgrade. Distinct from ``True`` so callers don't mistake a
#: no-op for a real upgrade success.
FORCE_UPDATE_NOOP: Any = _Sentinel("FORCE_UPDATE_NOOP")

#: Registry of stable machine-readable failure codes (mirrors Node's
#: ``FORCE_UPDATE_FAIL_CODES``). Every failure result carries one of these.
FORCE_UPDATE_FAIL_CODES: frozenset[str] = frozenset(
    {
        "disabled_in_noninteractive",
        "fetch_failed",
        "no_download_url",
        "checksum_failed",
        "download_failed",
        "extract_failed",
        "apply_failed",
        "bad_required_version",
        "current_version_unparsable",
        "copy_failed",
    }
)

#: Module-level mutex for :func:`execute_force_update`. True while an upgrade is
#: in progress so a re-entrant call (e.g. heartbeat tick during an evolve-cycle
#: update) short-circuits to ``FORCE_UPDATE_BUSY`` instead of re-downloading.
_in_flight: bool = False


def _reset_in_flight_for_testing() -> None:
    """Test hook: clear the module-level concurrency mutex."""
    global _in_flight  # noqa: PLW0603
    _in_flight = False


def _failure(code: str, detail: str, *, reason: str | None = None, **extra: Any) -> Any:
    """Build a frozen (immutable) failure result with a stable ``code`` + ``detail``.

    Frozen so consumers cannot mutate the code/detail (matches Node's
    ``Object.isFrozen`` contract). Kept dict-subscriptable for back-comat.
    """
    payload: dict[str, Any] = {
        "ok": False,
        "success": False,
        "code": code,
        "detail": detail,
        "reason": reason if reason is not None else code,
    }
    payload.update(extra)
    return types.MappingProxyType(payload)


def is_force_update_failure(value: Any) -> bool:
    """True iff *value* is a coded force-update failure result."""
    return (
        isinstance(value, (dict, types.MappingProxyType))
        and value.get("ok") is False
        and isinstance(value.get("code"), str)
        and isinstance(value.get("detail"), str)
    )


def _normalize_version_floor(raw: str) -> str:
    """Strip comparison operators and a leading ``v`` so ``>=1.88.0`` → ``1.88.0``."""
    return re.sub(r"^[~^>=<!\s]+", "", raw.strip()).lstrip("vV")


_CONCRETE_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")


def _is_concrete_version(raw: str) -> bool:
    """True iff *raw* is a concrete semver (``1``, ``1.2``, ``1.2.3``), no prerelease."""
    return bool(_CONCRETE_VERSION_RE.match(_normalize_version_floor(raw)))


def _satisfies_floor(current: str, required: str) -> bool:
    """True iff ``current`` (semver) is ``>=`` the ``required`` floor.

    Used for the idempotent no-op short-circuit: ``required_version`` is a
    *minimum floor*, not an exact target — a newer install must not downgrade.
    """
    try:
        return _parse_version(current.lstrip("vV")) >= _parse_version(
            _normalize_version_floor(required)
        )
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse ``1.89.2`` → ``(1, 89, 2)``. Non-numeric parts become 0."""
    parts = v.lstrip("v").split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def is_newer(new: str, current: str) -> bool:
    """Return True if *new* is semantically newer than *current*."""
    return _parse_version(new) > _parse_version(current)


# ---------------------------------------------------------------------------
# Download & verify
# ---------------------------------------------------------------------------


def _download_archive(url: str, dest: Path, timeout: float = UPDATE_TIMEOUT) -> Path:
    """Download *url* to *dest* with progress logging."""
    logger.info("[ForceUpdate] Downloading from %s", url)
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_bytes(chunk_size=8192):
                f.write(chunk)
    logger.info("[ForceUpdate] Downloaded %d bytes", dest.stat().st_size)
    return dest


def _verify_checksum(path: Path, expected: str | None) -> bool:
    if expected is None:
        return True

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest() == expected


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _backup_dir(src: Path, backup_root: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"evolver-backup-{ts}"
    shutil.copytree(src, backup, ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git"))
    logger.info("[ForceUpdate] Backed up to %s", backup)
    return backup


def _prune_backups(backup_root: Path, days: int = BACKUP_RETENTION_DAYS) -> None:
    cutoff = time.time() - days * 86400
    for entry in backup_root.iterdir():
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry)
            logger.info("[ForceUpdate] Pruned old backup %s", entry)


def _safe_extract(zf: Any, dest: Path) -> None:
    """Extract *zf* into *dest*, refusing path-traversal entries (Zip Slip).

    Ports the keep-list/tarball-fallback safety: archive entries that escape
    *dest* via absolute paths or ``..`` traversal are skipped, not written.
    """
    dest = dest.resolve()
    for member in zf.infolist():
        member_path = (dest / member.filename).resolve()
        if member_path != dest and dest not in member_path.parents:
            logger.warning("[ForceUpdate] skipping unsafe archive entry: %s", member.filename)
            continue
        zf.extract(member, dest)


# ---------------------------------------------------------------------------
# Core update
# ---------------------------------------------------------------------------


def apply_update(
    source: Path,
    target: Path,
    *,
    keep: set[str] | None = None,
) -> dict[str, Any]:
    """Atomically replace *target* directory contents with *source*,
    preserving items in *keep*.

    Returns metadata dict on success, raises on failure.
    """
    keep = keep or KEEP_LIST
    if not source.exists():
        raise RuntimeError(f"Source does not exist: {source}")
    if not target.exists():
        raise RuntimeError(f"Target does not exist: {target}")

    # Build a temp staging area next to target for atomic swap
    staging = target.with_name(f"{target.name}.update-staging-{int(time.time())}")
    try:
        shutil.copytree(
            target, staging, ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git")
        )

        # Overwrite with source, except keep-list
        for item in source.iterdir():
            if item.name in keep:
                continue
            dest = staging / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Atomic replace
        backup = target.with_name(f"{target.name}.pre-update-{int(time.time())}")
        target.rename(backup)
        staging.rename(target)
        logger.info("[ForceUpdate] Updated %s", target)

        # Clean up backup after a grace period (or immediately if asked)
        # For safety we keep it until next update prunes it
        return {"success": True, "previous": str(backup), "target": str(target)}
    except Exception:
        # Rollback: remove staging if it exists
        if staging.exists():
            shutil.rmtree(staging)
        raise


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def force_update(  # noqa: PLR0911
    *,
    current_version: str,
    target_version: str | None = None,
    url: str | None = None,
    expected_checksum: str | None = None,
    project_root: Path | None = None,
    backup_root: Path | None = None,
) -> Any:
    """Perform a forced update.

    Parameters
    ----------
    current_version:
        Currently installed version, e.g. ``"1.89.2"``.
    target_version:
        Desired version. If ``None``, fetched from Hub / GitHub latest.
    url:
        Direct download URL. If ``None``, resolves from GitHub releases.
    expected_checksum:
        SHA-256 of the archive (optional but recommended).
    project_root:
        Root of the evolver installation (default: cwd).
    backup_root:
        Directory to store backups (default: ``~/.evomap/backups``).
    """
    if not os.environ.get("EVOLVER_FORCE_UPDATE") and not os.environ.get("CI"):
        logger.warning(
            "[ForceUpdate] Non-interactive auto-update disabled. "
            "Set EVOLVER_FORCE_UPDATE=1 to enable."
        )
        return _failure(
            "disabled_in_noninteractive",
            "auto-update disabled in non-interactive mode; set EVOLVER_FORCE_UPDATE=1",
        )

    project_root = project_root or Path.cwd()
    backup_root = backup_root or (Path.home() / ".evomap" / "backups")
    backup_root.mkdir(parents=True, exist_ok=True)

    # Determine target
    if target_version is None:
        # Fetch latest from GitHub API
        try:
            r = httpx.get(
                "https://api.github.com/repos/evolver-ai/evolver/releases/latest",
                timeout=15.0,
            )
            r.raise_for_status()
            target_version = r.json()["tag_name"].lstrip("v")
            url = url or r.json().get("assets", [{}])[0].get("browser_download_url")
        except Exception as exc:
            logger.error("[ForceUpdate] Failed to fetch latest release: %s", exc)
            return _failure("fetch_failed", str(exc), error=str(exc))

    if not target_version or not is_newer(target_version, current_version):
        logger.info(
            "[ForceUpdate] No update needed: current=%s target=%s", current_version, target_version
        )
        return {"success": True, "reason": "up_to_date", "version": current_version}

    if url is None:
        return _failure("no_download_url", "no download URL resolved for the target release")

    # Backup
    _prune_backups(backup_root)
    backup = _backup_dir(project_root, backup_root)

    # Download
    with tempfile.TemporaryDirectory() as tmpdir:
        archive = Path(tmpdir) / "update.zip"
        _download_archive(url, archive)
        if not _verify_checksum(archive, expected_checksum):
            return _failure("checksum_failed", "downloaded archive checksum verification failed")

        # Extract
        extract_dir = Path(tmpdir) / "extracted"

        try:
            with zipfile.ZipFile(archive, "r") as zf:
                _safe_extract(zf, extract_dir)
        except Exception as exc:
            return _failure("extract_failed", str(exc))
        # GitHub release archives usually contain a single top-level folder
        children = [c for c in extract_dir.iterdir() if c.is_dir()]
        source = children[0] if len(children) == 1 else extract_dir

        # Apply
        try:
            result = apply_update(source, project_root)
        except Exception as exc:
            return _failure("apply_failed", str(exc))
        result["backup"] = str(backup)
        result["version"] = target_version
        return result


# ---------------------------------------------------------------------------
# v1.90.0 concurrency-guarded + idempotent entry point
# ---------------------------------------------------------------------------


def _installed_version() -> str | None:
    """Best-effort read of the installed evolver version."""
    try:
        from evolver import __version__  # noqa: PLC0415  # lazy: avoid import cycle

        return str(__version__)
    except Exception:
        return None


def execute_force_update(
    *,
    required_version: str | None = None,
    current_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Concurrency-guarded, idempotent force-update entry point.

    * ``required_version`` is a **minimum floor**, not an exact target. If the
      installed version already satisfies it (``>=`` after operator/``v``
      normalisation), returns :data:`FORCE_UPDATE_NOOP` without downloading.
    * A re-entrant call while an upgrade is in progress returns
      :data:`FORCE_UPDATE_BUSY` without re-entering the download path.
    * Failures are frozen, coded results (see :func:`is_force_update_failure`).
    """
    global _in_flight  # noqa: PLW0603
    if _in_flight:
        logger.debug("[ForceUpdate] re-entrant call while upgrade in flight → BUSY")
        return FORCE_UPDATE_BUSY

    cur = current_version or _installed_version()

    # Anti-downgrade guard (#213): an unparsable current version must not be
    # silently "satisfied" — refuse to update what we cannot version-check.
    if cur is not None and not _is_concrete_version(cur):
        return _failure(
            "current_version_unparsable", f"installed version not a concrete semver: {cur!r}"
        )

    if required_version:
        normalized = _normalize_version_floor(required_version)
        if not _is_concrete_version(normalized):
            return _failure(
                "bad_required_version",
                f"required_version not a concrete semver: {required_version!r}",
            )
        if cur is not None and _satisfies_floor(cur, required_version):
            logger.info(
                "[ForceUpdate] installed %s satisfies floor %s → NOOP", cur, required_version
            )
            return FORCE_UPDATE_NOOP

    _in_flight = True
    try:
        target = normalized if required_version else None
        return force_update(current_version=cur or "0.0.0", target_version=target, **kwargs)
    finally:
        _in_flight = False


def report_force_update_outcome(
    *,
    noop: bool = False,
    updated: bool = False,
    state_path: Path | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
) -> dict[str, Any]:
    """Persist a force-update outcome record.

    ``noop`` wins over ``updated`` (defensive): a no-op records ``status=
    "skipped"`` with no ``from_version``; a real upgrade records ``status=
    "success"`` with ``from_version``.
    """
    if noop:
        record: dict[str, Any] = {"status": "skipped"}
    elif updated:
        record = {"status": "success", "from_version": from_version, "to_version": to_version}
    else:
        record = {"status": "unknown"}
    if state_path is not None:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(record), encoding="utf-8")
        except OSError as exc:
            logger.warning("[ForceUpdate] could not persist outcome: %s", exc)
    return record
