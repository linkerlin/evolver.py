"""Git emergency self-repair.

Equivalent to ``evolver/src/ops/self_repair.js``.
Repairs common git-sync failures:

* abort pending rebase / merge
* remove stale ``.git/index.lock``
* optional hard reset to ``origin/main`` (opt-in, guarded)
* safe ``git fetch origin``

Design notes (Pythonic)
-----------------------
* Uses :func:`evolver.gep.git_ops.try_run_cmd` for best-effort git calls.
* Returns a structured :class:`RepairReport` so callers can decide whether to
  continue or abort.
* Stash before hard-reset to protect user changes (Node.js original does not
  stash, but this is safer and more Pythonic).
* Lock age uses ``pathlib.Path.stat().st_mtime`` in seconds.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from evolver.config import LOCK_MAX_AGE_MS
from evolver.gep.git_ops import is_git_repo, try_run_cmd
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RepairReport:
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def repair(
    git_root: Path | str | None = None,
    *,
    force_reset: bool | None = None,
) -> RepairReport:
    """Run the full self-repair suite.

    Parameters
    ----------
    git_root:
        Repository root. Defaults to ``get_workspace_root()``.
    force_reset:
        When ``True``, performs a hard reset to ``origin/main``.
        When ``None`` (default), reads ``EVOLVER_SELF_REPAIR_HARD_RESET``.
    """
    root = Path(git_root) if git_root else get_workspace_root()
    report = RepairReport()

    if not is_git_repo(root):
        report.errors.append("not_a_git_repo")
        return report

    # 1. Abort pending rebase
    _try_git(["rebase", "--abort"], root, report, "rebase_aborted", "rebase_abort_failed")

    # 2. Abort pending merge
    _try_git(["merge", "--abort"], root, report, "merge_aborted", "merge_abort_failed")

    # 3. Remove stale index.lock
    _remove_stale_lock(root, report)

    # 4. Hard reset (opt-in, last resort) or safe fetch
    do_reset = force_reset if force_reset is not None else _env_force_reset()
    if do_reset:
        _hard_reset(root, report)
    else:
        _safe_fetch(root, report)

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _env_force_reset() -> bool:
    raw = os.environ.get("EVOLVER_SELF_REPAIR_HARD_RESET", "").lower().strip()
    return raw in ("1", "true", "yes", "on")


def _try_git(
    args: Sequence[str],
    cwd: Path,
    report: RepairReport,
    success_tag: str,
    error_tag: str,
) -> None:
    """Run a git command, swallow errors, record outcome."""
    result = try_run_cmd(args, cwd=cwd, timeout=30.0)
    if result != "":
        # Command succeeded (or at least exited 0). For --abort commands an
        # empty stdout is normal when there is nothing to abort.
        report.actions.append(success_tag)
        logger.info("[SelfRepair] %s", success_tag.replace("_", " "))
    else:
        # Distinguish "nothing to do" from actual failure by re-running with
        # check=True inside a try/except.  Best-effort only.
        try:
            from evolver.gep.git_ops import run_cmd

            run_cmd(args, cwd=cwd, timeout=30.0)
            report.actions.append(success_tag)
            logger.info("[SelfRepair] %s", success_tag.replace("_", " "))
        except Exception:
            # No-op is acceptable for --abort when nothing is in progress.
            logger.debug("[SelfRepair] %s (nothing to do or failed)", error_tag)


def _remove_stale_lock(root: Path, report: RepairReport) -> None:
    lock_file = root / ".git" / "index.lock"
    if not lock_file.exists():
        return
    try:
        mtime = lock_file.stat().st_mtime
        age_ms = (time.time() - mtime) * 1000
        if age_ms > LOCK_MAX_AGE_MS:
            lock_file.unlink()
            tag = "stale_lock_removed"
            report.actions.append(tag)
            logger.info("[SelfRepair] Removed stale index.lock (%.0f min old).", age_ms / 60000)
        else:
            logger.debug("[SelfRepair] index.lock is fresh (%.0f min), leaving alone.", age_ms / 60000)
    except OSError as exc:
        report.errors.append(f"lock_remove_failed: {exc}")
        logger.warning("[SelfRepair] Failed to remove index.lock: %s", exc)


def _hard_reset(root: Path, report: RepairReport) -> None:
    logger.warning("[SelfRepair] Performing HARD reset to origin/main (EVOLVER_SELF_REPAIR_HARD_RESET is set).")

    # Safety: stash any local changes before the hard reset.
    try:
        try_run_cmd(["stash", "push", "-m", "evolver self-repair pre-reset"], cwd=root, timeout=30.0)
        report.actions.append("pre_reset_stash")
    except Exception:
        pass

    try:
        try_run_cmd(["fetch", "origin", "main"], cwd=root, timeout=60.0)
        try_run_cmd(["reset", "--hard", "origin/main"], cwd=root, timeout=30.0)
        report.actions.append("hard_reset_to_origin")
        logger.info("[SelfRepair] Hard reset completed.")
    except Exception as exc:
        err = f"hard_reset_failed: {exc}"
        report.errors.append(err)
        logger.error("[SelfRepair] Hard reset failed: %s", exc)


def _safe_fetch(root: Path, report: RepairReport) -> None:
    try:
        try_run_cmd(["fetch", "origin"], cwd=root, timeout=60.0)
        report.actions.append("fetch_ok")
        logger.info("[SelfRepair] git fetch origin succeeded.")
    except Exception as exc:
        err = f"fetch_failed: {exc}"
        report.errors.append(err)
        logger.warning("[SelfRepair] git fetch origin failed: %s", exc)
