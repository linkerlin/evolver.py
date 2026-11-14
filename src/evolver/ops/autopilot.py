"""``evolver up`` 的自适应滑动会话与空转休眠器 (P0-2, 支柱零).

Python-native new module (no Node.js equivalent — cf. evolve/runner.py's
legacy interval wait, which this module replaces under ``autopilot=True``).

Two policies layered on the daemon loop:

- **Sliding session**: the paired session budget stays frozen (only a human
  raises it); when a session exhausts its budget *with net gain*, the
  autopilot closes it and slides a fresh one open — no manual
  ``session start`` / ``extend`` / ``accept``.
- **Dormancy**: three consecutive no-progress rounds stretch the sleep
  interval; a fresh git commit or a fresh signal file wakes the loop at once.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Final

#: No-progress rounds before the loop goes dormant.
DORMANT_AFTER_ROUNDS: Final = 3
#: Sleep stretch per dormant round (exponential from the base interval).
DORMANT_BACKOFF: Final = 2.0
#: Upper bound for a dormant sleep slice (wake checks run between slices).
MAX_SLEEP_S: Final = 300.0


def _events_path() -> Path:
    from evolver.gep.paths import get_gep_assets_dir

    return Path(get_gep_assets_dir()) / "events.jsonl"


def _signals_mtime() -> float:
    from evolver.gep.paths import get_gep_assets_dir

    path = Path(get_gep_assets_dir()) / "pending_signals.json"
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _git_head(repo: Path) -> str:
    from evolver.gep.git_ops import git_head

    return git_head(repo)


def _success_settle_count() -> int:
    """Success-settled rounds in the event log tail (progress = net gain)."""
    events = _events_path()
    if not events.is_file():
        return 0
    try:
        with events.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()[-200:]
    except OSError:
        return 0
    n = 0
    for line in lines:
        if '"status": "success"' in line or '"status":"success"' in line:
            n += 1
    return n


class Dormancy:
    """No-progress streak tracking + wakeable dormant sleep.

    Progress = a fresh commit, a fresh signal, or a NEW success-settled
    round. Mere event-log churn (failure rounds append events too) is NOT
    progress — round-121 review fix."""

    _EVENTS_SAMPLE: Final = 200

    def __init__(self, *, repo: Path | None = None) -> None:
        self.repo = repo or Path.cwd()
        self.no_progress = 0
        self._last_head = _git_head(self.repo)
        self._last_signals_mtime = _signals_mtime()
        self._last_success_count = _success_settle_count()

    def observe(self) -> bool:
        """Compare runtime state against the last check; True = progress."""
        progressed = False
        head = _git_head(self.repo)
        if head and head != self._last_head:
            progressed = True
        self._last_head = head
        mtime = _signals_mtime()
        if mtime > self._last_signals_mtime:
            progressed = True
        self._last_signals_mtime = mtime
        count = _success_settle_count()
        if count > self._last_success_count:
            progressed = True
        self._last_success_count = count
        self.no_progress = 0 if progressed else self.no_progress + 1
        return progressed

    @property
    def dormant(self) -> bool:
        return self.no_progress >= DORMANT_AFTER_ROUNDS

    def sleep_s(self, base_interval: float) -> float:
        if not self.dormant:
            return base_interval
        stretch = DORMANT_BACKOFF ** (self.no_progress - DORMANT_AFTER_ROUNDS + 1)
        return min(base_interval * stretch, MAX_SLEEP_S)

    async def wait(self, shutdown: asyncio.Event, base_interval: float) -> None:
        """Sleep until the next cycle, waking early on new work while dormant."""
        remaining = self.sleep_s(base_interval)
        while remaining > 0:
            if shutdown.is_set():
                return
            if self.dormant:
                if self._woke_early():
                    self.no_progress = 0
                    return
            slice_s = min(remaining, 2.0 if self.dormant else remaining)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(shutdown.wait(), timeout=slice_s)
            remaining -= slice_s

    def _woke_early(self) -> bool:
        head = _git_head(self.repo)
        if head and head != self._last_head:
            return True
        if _signals_mtime() > self._last_signals_mtime:
            return True
        return _success_settle_count() > self._last_success_count


class SessionSlider:
    """Keep a paired session alive automatically, within its frozen budget."""

    def __init__(self) -> None:
        self._session: Any | None = None

    def ensure(self) -> dict[str, Any] | None:
        """A running session, opening one when none is active. Never raises."""
        try:
            from evolver.gep.evolution_session import RUNNING, EvolutionSession

            session = EvolutionSession()
            run = session.latest_run()
            if isinstance(run, dict) and run.get("status") == RUNNING:
                self._session = session
                return run
            fresh = session.start_run("autopilot")
            self._session = session
            return fresh
        except Exception:
            # Sessions are bookkeeping, not the loop's spine — a refusal
            # (lock held, store trouble) must never stop the cycle.
            self._session = None
            return None

    def after_cycle(self, *, promoted: bool | None = None) -> None:
        """Slide a fresh session open when the budget was spent with gain.

        ``promoted`` defaults to reading the solidify settle ledger: the
        runner's ctx never carries solidify results (they settle out-of-band
        via MCP/CLI), so the loop asks the ledger directly."""
        if promoted is None:
            try:
                from evolver.gep.solidify import _read_solidify_state

                state = _read_solidify_state() or {}
                last = state.get("last_solidify") or {}
                promoted = bool(last.get("run_id")) and str(last.get("outcome")) != "failed"
            except Exception:
                promoted = False
        if not promoted:
            return
        try:
            from evolver.gep.evolution_session import INCOMPLETE, RUNNING, EvolutionSession

            session = EvolutionSession()
            run = session.latest_run()
            if isinstance(run, dict) and run.get("status") == RUNNING:
                return
            if isinstance(run, dict) and run.get("status") == INCOMPLETE:
                # Budget exhausted mid-session with net gain: slide a new one.
                session.start_run("autopilot-renew")
                self._session = session
        except Exception:
            self._session = None


__all__ = ["DORMANT_AFTER_ROUNDS", "Dormancy", "SessionSlider"]
