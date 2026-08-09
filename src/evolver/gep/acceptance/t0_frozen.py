"""T0 held-out tier: frozen regression snapshot + pytest pass-rate runner.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint A1).

T0 is the always-on regression floor: at cycle start the current executable
test set is content-addressed-frozen (read-only); a candidate mutation must
not lower T0's pass rate. The freeze guarantees denominator stability across
baseline/candidate (constraint: ``assert_same_denominators``), since both
evaluate the same frozen test-ID set.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERROR_RE = re.compile(r"(\d+)\s+errors?")


def snapshot_hash(test_ids: list[str]) -> str:
    """Stable content hash of the test-ID set (sorted; order-independent)."""
    payload = "\n".join(sorted(test_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def freeze_snapshot(test_ids: list[str], snapshot_dir: Path) -> Path:
    """Freeze *test_ids* to ``<snapshot_dir>/t0_<hash>.txt`` (idempotent)."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"t0_{snapshot_hash(test_ids)}.txt"
    if not path.exists():
        path.write_text("\n".join(sorted(test_ids)), encoding="utf-8")
    return path


def load_snapshot(path: Path) -> list[str]:
    """Read a frozen snapshot back into a test-ID list."""
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def parse_pytest_summary(stdout: str, total: int) -> tuple[int, int]:
    """Extract ``(passed, total)`` from a pytest summary line.

    *total* is the frozen snapshot size (denominator), kept stable across
    baseline/candidate. *passed* is parsed from ``"N passed"``. If parsing
    fails, passed defaults to 0 (fail-safe: treat as regression).
    """
    if total == 0:
        return (0, 0)
    m = _PASSED_RE.search(stdout)
    passed = int(m.group(1)) if m else 0
    return (passed, total)


def discover_test_ids(cwd: Path, *, timeout_s: float = 60.0) -> list[str]:
    """Collect pytest node IDs via ``pytest --collect-only -q`` (sorted)."""
    proc = subprocess.run(
        ["pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        shell=False,
    )
    ids = [
        ln.strip()
        for ln in (proc.stdout or "").splitlines()
        if "::" in ln and not ln.strip().startswith(" ")
    ]
    return sorted(ids)


def run_pass_rate(
    test_ids: list[str],
    cwd: Path,
    *,
    timeout_s: float = 120.0,
) -> tuple[int, int]:
    """Run pytest on *test_ids*; return ``(passed, total)``.

    *total* is ``len(test_ids)`` (the frozen denominator). Each ID is passed
    verbatim to pytest; collection failures degrade passed toward 0.
    """
    total = len(test_ids)
    if total == 0:
        return (0, 0)
    try:
        proc = subprocess.run(
            ["pytest", *test_ids, "-q", "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
        return parse_pytest_summary(proc.stdout or "", total)
    except (subprocess.TimeoutExpired, OSError):
        return (0, total)


__all__ = [
    "discover_test_ids",
    "freeze_snapshot",
    "load_snapshot",
    "parse_pytest_summary",
    "run_pass_rate",
    "snapshot_hash",
]
