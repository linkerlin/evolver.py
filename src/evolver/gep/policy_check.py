"""Policy enforcement engine — safety gate before solidify.

Equivalent to ``evolver/src/gep/policyCheck.js`` (obfuscated core).
Runs a suite of checks before allowing a mutation to be solidified:
blast-radius limits, secret leak detection, protected-path guards,
and rollback safety.

Design notes (Pythonic)
-----------------------
* Returns a structured ``PolicyReport`` dataclass so callers can decide
  whether to abort, warn, or proceed.
* Uses ``pathlib.Path`` for all path checks.
* Secret scanning delegates to :mod:`evolver.gep.sanitize`.
* Rollback safety verifies that tracked changes can be reverted without
  losing user data.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.config import BLAST_RADIUS_HARD_CAP_FILES, BLAST_RADIUS_HARD_CAP_LINES
from evolver.gep.git_ops import (
    git_list_changed_files,
    git_list_untracked_files,
    is_critical_protected_path,
)
from evolver.gep.paths import get_workspace_root
from evolver.gep.sanitize import full_leak_check

logger = logging.getLogger(__name__)

# Additional paths that should never be modified by evolver itself
_SELF_PROTECTED_PREFIXES = ("evolver/",)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PolicyViolation:
    rule: str
    severity: str  # critical | warning
    message: str


@dataclass
class PolicyReport:
    ok: bool
    violations: list[PolicyViolation] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(v.severity == "critical" for v in self.violations)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_policy(
    *,
    diff_text: str | None = None,
    changed_files: Sequence[str] | None = None,
    untracked_files: Sequence[str] | None = None,
    max_files: int | None = None,
    max_lines: int | None = None,
) -> PolicyReport:
    """Run the full policy-check suite.

    Parameters
    ----------
    diff_text:
        Raw git diff text (used for secret scanning).
    changed_files:
        List of changed file paths (relative). If omitted, computed from git.
    untracked_files:
        List of untracked file paths (relative). If omitted, computed from git.
    max_files:
        Hard cap on number of files touched. Defaults to ``BLAST_RADIUS_HARD_CAP_FILES``.
    max_lines:
        Hard cap on lines changed. Defaults to ``BLAST_RADIUS_HARD_CAP_LINES``.
    """
    violations: list[PolicyViolation] = []
    cwd = get_workspace_root()

    changed = list(changed_files) if changed_files is not None else git_list_changed_files(cwd)
    untracked = (
        list(untracked_files) if untracked_files is not None else git_list_untracked_files(cwd)
    )
    all_files = list(dict[str, Any].fromkeys(changed + untracked))  # preserve order, dedup

    # 1. Blast radius
    _check_blast_radius(all_files, changed, untracked, max_files, max_lines, violations)

    # 2. Protected paths (critical files + self-protection)
    _check_protected_paths(all_files, cwd, violations)

    # 3. Secret leak detection
    _check_secret_leaks(diff_text, violations)

    # 4. Rollback safety (stash path)
    _check_rollback_safety(changed, untracked, violations)

    report = PolicyReport(
        ok=not any(v.severity == "critical" for v in violations), violations=violations
    )
    if not report.ok:
        logger.warning(
            "[PolicyCheck] %d critical violation(s) found",
            len([v for v in violations if v.severity == "critical"]),
        )
    return report


# ---------------------------------------------------------------------------
# Internal checks
# ---------------------------------------------------------------------------


def _check_blast_radius(
    all_files: list[str],
    changed: list[str],
    untracked: list[str],
    max_files: int | None,
    max_lines: int | None,
    violations: list[PolicyViolation],
) -> None:
    file_cap = max_files if max_files is not None else BLAST_RADIUS_HARD_CAP_FILES
    line_cap = max_lines if max_lines is not None else BLAST_RADIUS_HARD_CAP_LINES

    if len(all_files) > file_cap:
        violations.append(
            PolicyViolation(
                rule="blast_radius_files",
                severity="critical",
                message=f"Touched {len(all_files)} files (cap={file_cap})",
            )
        )

    # Count lines in changed + untracked files
    cwd = get_workspace_root()
    total_lines = 0
    for rel in changed + untracked:
        p = cwd / rel
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                total_lines += sum(1 for _ in f)
        except OSError:
            pass

    if total_lines > line_cap:
        violations.append(
            PolicyViolation(
                rule="blast_radius_lines",
                severity="critical",
                message=f"Touched {total_lines} lines (cap={line_cap})",
            )
        )


def _check_protected_paths(
    all_files: list[str],
    cwd: Path,
    violations: list[PolicyViolation],
) -> None:
    for rel in all_files:
        # Critical files
        if is_critical_protected_path(rel):
            violations.append(
                PolicyViolation(
                    rule="protected_path",
                    severity="critical",
                    message=f"Modification of protected path blocked: {rel}",
                )
            )
            continue

        # Self-protection: evolver/ directory
        norm_rel = rel.replace("\\", "/")
        for prefix in _SELF_PROTECTED_PREFIXES:
            if norm_rel.startswith(prefix):
                violations.append(
                    PolicyViolation(
                        rule="self_protection",
                        severity="critical",
                        message=f"Modification of evolver own source blocked: {rel}",
                    )
                )
                break

        # Secret files
        name = Path(rel).name.lower()
        if name == ".env" or name.endswith(".key") or "secret" in name:
            violations.append(
                PolicyViolation(
                    rule="secret_file",
                    severity="critical",
                    message=f"Modification of secret file blocked: {rel}",
                )
            )


def _check_secret_leaks(diff_text: str | None, violations: list[PolicyViolation]) -> None:
    if not diff_text:
        return
    leak_report = full_leak_check(diff_text)
    if not leak_report["safe"]:
        for leak in leak_report.get("pattern_leaks", []):
            violations.append(
                PolicyViolation(
                    rule="secret_leak",
                    severity="critical",
                    message=(
                        f"Potential secret leak detected: {leak['type']} "
                        f"at offset {leak['start']}"
                    ),
                )
            )
        for leak in leak_report.get("env_leaks", []):
            violations.append(
                PolicyViolation(
                    rule="env_leak",
                    severity="critical",
                    message=f"Env value leak detected: {leak['key']}",
                )
            )


def _check_rollback_safety(
    changed: list[str],
    untracked: list[str],
    violations: list[PolicyViolation],
) -> None:
    mode = os.environ.get("EVOLVER_ROLLBACK_MODE", "stash").lower().strip()
    if mode == "none":
        violations.append(
            PolicyViolation(
                rule="rollback_mode_none",
                severity="warning",
                message="Rollback mode is 'none' — changes cannot be auto-reverted",
            )
        )
        return

    # Check for untracked files that would be lost on hard reset
    if mode == "hard":
        if untracked:
            violations.append(
                PolicyViolation(
                    rule="rollback_hard_untracked",
                    severity="warning",
                    message=f"Hard reset would delete {len(untracked)} untracked file(s)",
                )
            )

    # Stash mode is generally safe for tracked files
    # but warn if there are uncommitted changes in protected files
    for rel in changed:
        if is_critical_protected_path(rel):
            violations.append(
                PolicyViolation(
                    rule="rollback_protected_change",
                    severity="warning",
                    message=f"Rollback may revert changes in protected file: {rel}",
                )
            )
