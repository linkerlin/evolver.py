"""Force update engine — self-updating evolver when Hub triggers version expiry.

Equivalent to Node's ``evolver/src/forceUpdate.js``.

Channels:
1. GitHub Release (default)
2. Manual URL (enterprise / internal deployments)

Safety:
- Semantic version comparison
- Atomic file replacement (temp + os.replace)
- File-lock concurrency guard
- Keep List: local state (memory/, .env*, USER.md, logs/, …) never overwritten
- Mid-copy wedge protection: commit markers (package.json / pyproject.toml)
  stay until the final atomic swap; partial failures leave the old install readable
- Install-guard fail-closed + bootstrap recovery when strong markers present
- Automatic rollback on failure
- Backup before update
"""

from __future__ import annotations

import contextlib
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Node v1.89.15 keep-list + Python install extras. Top-level names only.
KEEP_LIST: frozenset[str] = frozenset(
    {
        # Classic Node keep-list
        "node_modules",
        "memory",
        ".git",
        "MEMORY.md",
        # Extended keep-list (v1.89.15)
        ".env",
        ".env.local",
        "USER.md",
        ".evolver",
        "logs",
        # Python / evomap extras
        "skills",
        ".evomap",
        ".venv",
        "venv",
        "__pycache__",
    }
)

#: Commit markers are kept in place through delete+copy and swapped last
#: (mid-copy wedge fix). Either Node package.json or Python pyproject.toml.
COMMIT_MARKER_NAMES: frozenset[str] = frozenset({"package.json", "pyproject.toml"})

#: Bootstrap entry committed early so an interrupted update restarts through
#: recovery-capable code (Node index.js parity).
BOOTSTRAP_ENTRY_NAMES: frozenset[str] = frozenset({"index.js"})

FORCE_UPDATE_BACKUP_PREFIX: str = ".evolver-force-update-backup-"
FORCE_UPDATE_JOURNAL_FILE: str = ".evolver-force-update-journal.json"
MAX_INSTALL_MARKER_BYTES: int = 1024 * 1024

#: Strong install markers for bootstrap recovery when package.json is missing.
#: Required marker + ≥2 others (Node EVOLVER_INSTALL_MARKERS contract).
_INSTALL_MARKERS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("src/evolver/force_update.py", ("execute_force_update", "FORCE_UPDATE_FAIL_CODES"), True),
    ("src/evolver/gep/paths.py", ("get_repo_root", "get_evolver_install_root"), False),
    ("src/evolver/gep/a2a_protocol.py", ("report_force_update_outcome", "A2A"), False),
    ("pyproject.toml", ("evolver", "name"), False),
)

BACKUP_RETENTION_DAYS = 7
UPDATE_TIMEOUT = 120.0

# Test hooks: injectable copy/rename so mid-copy failure can be simulated.
_copy_tree_fn: Callable[[Path, Path], None] | None = None
_copy_file_fn: Callable[[Path, Path], None] | None = None
_rename_fn: Callable[[Path, Path], None] | None = None


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
        "delete_failed",
        "install_guard_name_mismatch",
        "install_guard_unreadable",
        "download_incomplete",
        "downloaded_package_name_mismatch",
        "downloaded_version_mismatch",
    }
)

#: Module-level mutex for :func:`execute_force_update`. True while an upgrade is
#: in progress so a re-entrant call (e.g. heartbeat tick during an evolve-cycle
#: update) short-circuits to ``FORCE_UPDATE_BUSY`` instead of re-downloading.
_in_flight: bool = False


def _reset_in_flight_for_testing() -> None:
    """Test hook: clear the module-level concurrency mutex and copy hooks."""
    global _in_flight, _copy_tree_fn, _copy_file_fn, _rename_fn  # noqa: PLW0603
    _in_flight = False
    _copy_tree_fn = None
    _copy_file_fn = None
    _rename_fn = None


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


# ---------------------------------------------------------------------------
# Keep-list / entry classification (v1.89.15)
# ---------------------------------------------------------------------------


def is_force_update_keep_entry(name: str) -> bool:
    """True iff *name* is a top-level keep-list entry (local state)."""
    return name in KEEP_LIST


def is_force_update_bootstrap_entry(name: str) -> bool:
    """True iff *name* is a recovery bootstrap entry (committed early)."""
    return name in BOOTSTRAP_ENTRY_NAMES


def is_force_update_commit_marker(name: str) -> bool:
    """True iff *name* is an install commit marker (swapped last)."""
    return name in COMMIT_MARKER_NAMES


def is_force_update_internal_entry(name: str) -> bool:
    """True for force-update journal / in-progress backup directories."""
    return name == FORCE_UPDATE_JOURNAL_FILE or name.startswith(FORCE_UPDATE_BACKUP_PREFIX)


def _should_skip_payload_entry(name: str) -> bool:
    """Skip keep-list, bootstrap, internal, and commit-marker entries in payload loops."""
    return (
        is_force_update_keep_entry(name)
        or is_force_update_bootstrap_entry(name)
        or is_force_update_internal_entry(name)
        or is_force_update_commit_marker(name)
    )


def _do_copy_file(src: Path, dst: Path) -> None:
    fn = _copy_file_fn
    if fn is not None:
        fn(src, dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _do_copy_tree(src: Path, dst: Path) -> None:
    fn = _copy_tree_fn
    if fn is not None:
        fn(src, dst)
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _do_rename(src: Path, dst: Path) -> None:
    """Rename/replace *src* → *dst*.

    Uses :func:`os.replace` so an existing destination is overwritten on
    Windows (``Path.rename`` raises WinError 183 when *dst* exists).
    """
    fn = _rename_fn
    if fn is not None:
        fn(src, dst)
        return
    os.replace(src, dst)


def _is_evolver_package_name(name: str | None) -> bool:
    return name in {"@evomap/evolver", "evolver"}


def _file_matches_install_marker(root: Path, rel: str, tokens: tuple[str, ...]) -> bool:
    path = root / rel
    try:
        if not path.is_file():
            return False
        if path.stat().st_size > MAX_INSTALL_MARKER_BYTES:
            return False
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return all(tok in content for tok in tokens)


def has_strong_evolver_install_markers(root: Path) -> bool:
    """True when enough evolver identity markers exist for bootstrap recovery."""
    matched = 0
    required_matched = False
    for rel, tokens, required in _INSTALL_MARKERS:
        if not _file_matches_install_marker(root, rel, tokens):
            continue
        matched += 1
        if required:
            required_matched = True
    return required_matched and matched >= 3


def _recover_package_commit_marker_if_missing(install_root: Path) -> bool:
    """Restore ``package.json`` from ``package.json.<pid>.evolver-old`` leftovers."""
    pkg_dst = install_root / "package.json"
    if pkg_dst.exists():
        return False
    try:
        entries = list(install_root.iterdir())
    except OSError:
        return False
    backups = sorted(
        e
        for e in entries
        if e.is_file() and re.fullmatch(r"package\.json\.\d+\.evolver-old", e.name)
    )
    for backup in reversed(backups):
        try:
            backup.rename(pkg_dst)
            logger.warning(
                "[ForceUpdate] Recovered package.json commit marker from %s", backup.name
            )
            return True
        except OSError:
            continue
    return False


def check_install_guard(install_root: Path) -> Any | None:
    """Fail-closed install-root guard.

    Returns ``None`` when the root is safe to update, else a frozen failure.
    Allows bootstrap recovery when package.json is unreadable but strong
    evolver markers are present (Node v1.89.15 contract).
    """
    pkg_path = install_root / "package.json"
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        name = pkg.get("name") if isinstance(pkg, dict) else None
        if not _is_evolver_package_name(str(name) if name is not None else None):
            logger.warning(
                "[ForceUpdate] Refusing — %s/package.json has name=%r, expected "
                "@evomap/evolver or evolver",
                install_root,
                name,
            )
            return _failure(
                "install_guard_name_mismatch",
                f'install root package.json name="{name}", expected "@evomap/evolver"',
            )
        return None
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError) as exc:
        if _recover_package_commit_marker_if_missing(install_root):
            return check_install_guard(install_root)
        if has_strong_evolver_install_markers(install_root):
            logger.warning(
                "[ForceUpdate] install package.json is unreadable, but strong "
                "evolver install markers are present; bootstrap recovery allowed"
            )
            return None
        logger.warning(
            "[ForceUpdate] Refusing — cannot read %s/package.json: %s", install_root, exc
        )
        return _failure(
            "install_guard_unreadable",
            f"cannot read install root package.json: {exc}",
        )


def _write_recovery_journal(
    backup_root: Path, required_version: str, previous_version: str
) -> None:
    journal = {
        "state": "precommit",
        "requiredVersion": required_version,
        "previousVersion": previous_version,
        "createdAt": int(time.time() * 1000),
    }
    path = backup_root / FORCE_UPDATE_JOURNAL_FILE
    path.write_text(json.dumps(journal), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _read_install_package_version(install_root: Path) -> str:
    try:
        pkg = json.loads((install_root / "package.json").read_text(encoding="utf-8"))
        if isinstance(pkg, dict) and pkg.get("version"):
            return str(pkg["version"])
    except (OSError, json.JSONDecodeError, TypeError, UnicodeError):
        pass
    return ""


def _commit_atomic_file_replacement(src: Path, dst: Path, tmp: Path, backup: Path) -> None:
    """Copy *src* → *dst* via tmp+rename; keep prior *dst* at *backup* if present."""
    if tmp.exists():
        tmp.unlink()
    if backup.exists():
        if backup.is_dir():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    _do_copy_file(src, tmp)
    if dst.exists() and dst.is_file():
        _do_copy_file(dst, backup)
    _do_rename(tmp, dst)


def _restore_file_backup_if_present(backup: Path | None, dst: Path) -> bool:
    if backup is None or not backup.exists():
        return False
    try:
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        _do_copy_file(backup, dst)
        return True
    except OSError:
        return False


def _restore_moved_entries(
    install_root: Path,
    moved: list[dict[str, Path | str]],
    copied_names: list[str],
) -> bool:
    ok = True
    seen: set[str] = set()
    for name in reversed(copied_names):
        if name in seen:
            continue
        seen.add(name)
        live = install_root / name
        try:
            if live.exists():
                if live.is_dir():
                    shutil.rmtree(live)
                else:
                    live.unlink()
        except OSError as exc:
            ok = False
            logger.warning("[ForceUpdate] rollback cleanup failed for %s: %s", name, exc)

    for entry in reversed(moved):
        name = str(entry["name"])
        live_path = Path(str(entry["live_path"]))
        backup_path = Path(str(entry["backup_path"]))
        try:
            if live_path.exists():
                if live_path.is_dir():
                    shutil.rmtree(live_path)
                else:
                    live_path.unlink()
            if backup_path.exists():
                _do_rename(backup_path, live_path)
        except OSError as exc:
            ok = False
            logger.warning("[ForceUpdate] rollback restore failed for %s: %s", name, exc)
    return ok


def install_downloaded_tree(  # noqa: PLR0911, PLR0912, PLR0915
    install_root: Path,
    temp_target: Path,
    *,
    required_version: str | None = None,
    success_label: str = "installed",
) -> Any:
    """Install a downloaded tree into *install_root* with mid-copy wedge safety.

    Ports Node ``_installDownloadedTree``:
    - Keep-list entries are never deleted or overwritten.
    - ``index.js`` (bootstrap) is committed early when present.
    - ``package.json`` / ``pyproject.toml`` stay until a final atomic swap.
    - Mid-copy failures roll back payload moves and leave the old commit marker.
    """
    install_root = Path(install_root)
    temp_target = Path(temp_target)
    phase = "parse"
    backup_root: Path | None = None
    moved_entries: list[dict[str, Path | str]] = []
    copied_entry_names: list[str] = []
    committed_index = False
    index_backup: Path | None = None
    package_backup: Path | None = None
    entry_name = ""

    try:
        pkg_src = temp_target / "package.json"
        if not pkg_src.is_file():
            return _failure("download_incomplete", "missing package.json in downloaded tree")
        try:
            tmp_pkg = json.loads(pkg_src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            return _failure("download_incomplete", f"unreadable package.json: {exc}")
        pkg_name = tmp_pkg.get("name") if isinstance(tmp_pkg, dict) else None
        if not isinstance(tmp_pkg, dict) or not _is_evolver_package_name(
            str(pkg_name or "") or None
        ):
            return _failure(
                "downloaded_package_name_mismatch",
                f'downloaded package.json name="{pkg_name}", expected "@evomap/evolver"',
            )
        version = str(tmp_pkg.get("version") or "")
        if not version:
            return _failure("download_incomplete", "downloaded package.json has no version field")
        if required_version and version != required_version:
            return _failure(
                "downloaded_version_mismatch",
                f"downloaded version={version!r}, expected {required_version}",
            )
        index_src = temp_target / "index.js"
        if not index_src.is_file():
            return _failure("download_incomplete", "missing/unreadable index.js in downloaded tree")

        phase = "delete"
        entries = list(install_root.iterdir())
        backup_root = Path(
            tempfile.mkdtemp(prefix=FORCE_UPDATE_BACKUP_PREFIX, dir=str(install_root))
        )
        prev_ver = _read_install_package_version(install_root)
        _write_recovery_journal(backup_root, required_version or version, prev_ver)

        index_dst = install_root / "index.js"
        index_tmp = install_root / f"index.js.{os.getpid()}.evolver-tmp"
        index_backup = backup_root / "index.js"
        try:
            phase = "copy"
            entry_name = "index.js commit"
            _commit_atomic_file_replacement(index_src, index_dst, index_tmp, index_backup)
            committed_index = True
        except OSError as exc:
            _restore_file_backup_if_present(index_backup, index_dst)
            if index_tmp.exists():
                with contextlib.suppress(OSError):
                    index_tmp.unlink()
            logger.warning("[ForceUpdate] index.js commit (atomic replace) failed: %s", exc)
            raise

        for entry in entries:
            e_name = entry.name
            if _should_skip_payload_entry(e_name):
                continue
            try:
                phase = "delete"
                entry_name = e_name
                live_path = install_root / e_name
                backup_path = backup_root / e_name
                _do_rename(live_path, backup_path)
                moved_entries.append(
                    {"name": e_name, "live_path": live_path, "backup_path": backup_path}
                )
            except OSError as exc:
                logger.warning("[ForceUpdate] backup move failed for %s: %s", e_name, exc)
                raise

        phase = "copy"
        for new_entry in temp_target.iterdir():
            n_name = new_entry.name
            if _should_skip_payload_entry(n_name):
                continue
            src = temp_target / n_name
            dst = install_root / n_name
            try:
                entry_name = n_name
                copied_entry_names.append(n_name)
                if src.is_dir():
                    _do_copy_tree(src, dst)
                else:
                    _do_copy_file(src, dst)
            except OSError as exc:
                logger.warning("[ForceUpdate] copy failed for %s: %s", n_name, exc)
                raise

        # Commit markers last (wedge fix).
        for marker_name in ("package.json", "pyproject.toml"):
            m_src = temp_target / marker_name
            if not m_src.is_file():
                continue
            m_dst = install_root / marker_name
            m_tmp = install_root / f"{marker_name}.{os.getpid()}.evolver-tmp"
            package_backup = backup_root / marker_name
            try:
                entry_name = f"{marker_name} commit"
                _commit_atomic_file_replacement(m_src, m_dst, m_tmp, package_backup)
            except OSError as exc:
                _restore_file_backup_if_present(package_backup, m_dst)
                if committed_index:
                    _restore_file_backup_if_present(index_backup, index_dst)
                if m_tmp.exists():
                    with contextlib.suppress(OSError):
                        m_tmp.unlink()
                logger.warning(
                    "[ForceUpdate] %s commit (atomic replace) failed: %s",
                    marker_name,
                    exc,
                )
                raise

        with contextlib.suppress(OSError):
            shutil.rmtree(temp_target)
        if backup_root is not None:
            try:
                shutil.rmtree(backup_root)
            except OSError as exc:
                logger.warning("[ForceUpdate] backup cleanup failed: %s", exc)

        logger.info("[ForceUpdate] %s: %s", success_label, version)
        return {"ok": True, "success": True, "version": version}
    except OSError as exc:
        if backup_root is not None:
            if committed_index:
                _restore_file_backup_if_present(index_backup, install_root / "index.js")
            if package_backup is not None:
                _restore_file_backup_if_present(package_backup, install_root / "package.json")
            restored = _restore_moved_entries(install_root, moved_entries, copied_entry_names)
            if restored:
                with contextlib.suppress(OSError):
                    shutil.rmtree(backup_root)
        detail_prefix = f"{entry_name}: " if entry_name else ""
        code = "delete_failed" if phase == "delete" else "copy_failed"
        return _failure(code, f"{detail_prefix}{exc}")
    except Exception as exc:
        if backup_root is not None:
            if committed_index:
                _restore_file_backup_if_present(index_backup, install_root / "index.js")
            _restore_moved_entries(install_root, moved_entries, copied_entry_names)
        return _failure("copy_failed", f"{entry_name}: {exc}" if entry_name else str(exc))


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
    keep: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Atomically replace *target* directory contents with *source*,
    preserving items in *keep* (defaults to :data:`KEEP_LIST`).

    Prefer :func:`install_downloaded_tree` for Node-style package installs that
    need mid-copy wedge protection (commit markers swapped last).

    Returns metadata dict on success, raises on failure.
    """
    keep_names = frozenset(keep) if keep is not None else KEEP_LIST
    if not source.exists():
        raise RuntimeError(f"Source does not exist: {source}")
    if not target.exists():
        raise RuntimeError(f"Target does not exist: {target}")

    # Build a temp staging area next to target for atomic swap
    staging = target.with_name(f"{target.name}.update-staging-{int(time.time())}")
    try:
        shutil.copytree(
            target,
            staging,
            ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git"),
        )

        # Overwrite with source, except keep-list (and never let release
        # archives clobber local state even when they ship those paths).
        for item in source.iterdir():
            if item.name in keep_names or is_force_update_internal_entry(item.name):
                continue
            dest = staging / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Atomic replace with restore-if-second-rename-fails (wedge-safe).
        backup = target.with_name(f"{target.name}.pre-update-{int(time.time())}")
        target.rename(backup)
        try:
            staging.rename(target)
        except OSError:
            # Second rename failed: put the original tree back.
            try:
                if staging.exists():
                    shutil.rmtree(staging)
            except OSError:
                pass
            backup.rename(target)
            raise
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

        # Prefer mid-copy-safe in-place install when the download looks like
        # a Node package tree (package.json + index.js); else staging swap.
        try:
            if (source / "package.json").is_file() and (source / "index.js").is_file():
                guard = check_install_guard(project_root)
                if guard is not None:
                    return guard
                result = install_downloaded_tree(
                    project_root,
                    source,
                    required_version=target_version,
                    success_label="force_update",
                )
                if is_force_update_failure(result):
                    return result
                if isinstance(result, dict):
                    out = dict(result)
                    out["backup"] = str(backup)
                    out["version"] = target_version
                    out["success"] = True
                    return out
                return result
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
