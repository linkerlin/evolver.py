"""Safety/yield layer that gates evolve.run().

Equivalent to evolver/src/evolve/guards.js.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass
class PreflightResult:
    abort: bool = False
    reason: str | None = None
    repair_loop_degraded: bool = False


@dataclass
class LoadSample:
    load1m: float
    load5m: float
    load15m: float


def detect_cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def get_system_load() -> LoadSample:
    cpu_count = detect_cpu_count()
    try:
        raw = os.getloadavg()  # type: ignore[attr-defined]
        loads = [min(float(x), 2.0 * cpu_count) for x in raw]
    except (AttributeError, OSError):
        loads = [0.0, 0.0, 0.0]
    return LoadSample(load1m=loads[0], load5m=loads[1], load15m=loads[2])


def get_default_load_max() -> float:
    return 0.9 if detect_cpu_count() == 1 else 1.5


def determine_bridge_enabled() -> bool:
    raw = os.environ.get("EVOLVE_BRIDGE")
    if raw is not None:
        return raw.lower() in ("1", "true", "yes", "on")
    return os.environ.get("OPENCLAW_WORKSPACE") is not None


def _dormant_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "dormant_hypothesis.json"


def write_dormant_hypothesis(payload: dict[str, Any]) -> None:
    path = _dormant_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload), encoding="utf-8")


def read_dormant_hypothesis() -> dict[str, Any] | None:
    import json

    path = _dormant_path()
    if not path.exists():
        return None
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def clear_dormant_hypothesis() -> None:
    path = _dormant_path()
    if path.exists():
        path.unlink()


def check_repair_loop_circuit_breaker(
    threshold: int | None = None,
    window: int = 10,
) -> dict[str, Any]:
    """Inspect asset-store history to detect repair loops.

    A repair loop is defined as ``threshold`` consecutive events whose
    mutation category is ``repair`` and whose outcome status is ``failed``.
    """
    from evolver.config import REPAIR_LOOP_THRESHOLD
    from evolver.gep.asset_store import read_all_events

    limit = threshold or REPAIR_LOOP_THRESHOLD
    events = read_all_events()
    if not events:
        return {"tripped": False, "consecutive": 0, "threshold": limit}

    # Look at the tail of events (most recent first)
    tail = list(reversed(events[-window:]))
    consecutive = 0
    for evt in tail:
        mut = evt.get("mutation") or {}
        cat = mut.get("category", "")
        status = (evt.get("outcome") or {}).get("status", "")
        if cat == "repair" and status == "failed":
            consecutive += 1
        else:
            break

    return {
        "tripped": consecutive >= limit,
        "consecutive": consecutive,
        "threshold": limit,
    }


def _load_max() -> float:
    raw = os.environ.get("EVOLVE_LOAD_MAX")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return get_default_load_max()


async def run_preflight_checks(is_loop: bool = False, is_dry_run: bool = False) -> PreflightResult:
    if is_dry_run:
        return PreflightResult(abort=False)
    sample = get_system_load()
    threshold = _load_max()
    if sample.load1m > threshold:
        return PreflightResult(
            abort=True,
            reason=f"system load {sample.load1m:.2f} exceeds threshold {threshold:.2f}",
        )
    cb = check_repair_loop_circuit_breaker()
    if cb["tripped"]:
        degraded_ok = os.environ.get("EVOLVER_REPAIR_LOOP_DEGRADED", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        reason = (
            f"repair loop detected ({cb['consecutive']}/{cb['threshold']} "
            "consecutive failed repair cycles)"
        )
        if degraded_ok:
            return PreflightResult(abort=False, reason=reason, repair_loop_degraded=True)
        return PreflightResult(abort=True, reason=reason)

    # User lock
    user_lock = Path(os.environ.get("EVOLVER_USER_LOCK", "")) or (
        Path.home() / ".evolver" / "user.lock"
    )
    if user_lock.exists():
        lock_eval = evaluate_user_lock(user_lock)
        if lock_eval.yield_required:
            return PreflightResult(
                abort=True,
                reason=f"user lock active ({lock_eval.reason}, age={lock_eval.age_ms}ms)",
            )

    # Release window
    release_eval = evaluate_release_window(None, None)
    if release_eval.yield_required:
        return PreflightResult(
            abort=True,
            reason=f"release window active ({release_eval.reason})",
        )

    return PreflightResult(abort=False)


@dataclass
class LockEvaluation:
    yield_required: bool
    reason: str
    age_ms: int | None = None


MIN_USER_LOCK_TTL_MS = 1_000


def evaluate_user_lock(
    lock_path: Path,
    now: float | None = None,
    ttl_ms: int = 60_000,
) -> LockEvaluation:
    if now is None:
        now = time.time() * 1000
    ttl_ms = max(ttl_ms, MIN_USER_LOCK_TTL_MS)
    if not lock_path.exists():
        return LockEvaluation(yield_required=False, reason="no_lock")
    try:
        mtime = lock_path.stat().st_mtime * 1000
        age_ms = int(now - mtime)
    except OSError:
        return LockEvaluation(yield_required=False, reason="stat_failed", age_ms=None)
    if age_ms < 0:
        return LockEvaluation(yield_required=True, reason="lock_active_future_mtime", age_ms=age_ms)
    if age_ms > ttl_ms:
        return LockEvaluation(yield_required=False, reason="lock_stale", age_ms=age_ms)
    return LockEvaluation(yield_required=True, reason="lock_active", age_ms=age_ms)


@dataclass
class ReleaseWindowResult:
    yield_required: bool
    reason: str


def evaluate_release_window(
    last_commit_subject: str | None,
    last_commit_unix_ts: float | None,
    now: float | None = None,
    window_ms: int = 5 * 60 * 1_000,
) -> ReleaseWindowResult:
    if window_ms == 0:
        return ReleaseWindowResult(yield_required=False, reason="disabled")
    if not last_commit_subject or last_commit_unix_ts is None:
        return ReleaseWindowResult(yield_required=False, reason="no_commit")
    if now is None:
        now = time.time() * 1000
    age_ms = int(now - last_commit_unix_ts * 1000)
    if age_ms < 0:
        return ReleaseWindowResult(yield_required=False, reason="future_commit")
    if age_ms > window_ms:
        return ReleaseWindowResult(yield_required=False, reason="window_passed")
    if last_commit_subject.lower().startswith("chore(release)"):
        return ReleaseWindowResult(yield_required=True, reason="release_window_active")
    return ReleaseWindowResult(yield_required=False, reason="not_release_commit")


# Interruptible sleep helpers
_active_sleeps: set[object] = set()


def sleep_ms(ms: float) -> None:
    """Sync blocking sleep; for async callers use asyncio.sleep."""
    time.sleep(max(0, ms) / 1000.0)


def _interrupt_guard_sleeps() -> None:
    """Placeholder for process wake hooks to interrupt guard sleeps."""
    pass
