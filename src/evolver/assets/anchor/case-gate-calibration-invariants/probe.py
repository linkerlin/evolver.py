"""Anchor probe: acceptance-gate calibration invariants (round-27).

Rounds 22-25 built the gate's noise-immunity stack -- chunk-level retry
(DEBUG #33), the rolling soak window (#35), and granularity-aware majority
flake adjudication (#36). Those semantics live only behind in-repo tests,
yet the whole acceptance/ tree is on the anchor trigger surface: a mutation
weakening both the gate and its tests would be waved through by the weakened
tests. This probe freezes the three semantics out-of-tree. The checked
functions are pure or patchable in-process, so no subprocess calls are made
by the probe itself. Exit 0 = pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _isolate(ws: Path) -> None:
    (ws / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "OPENCLAW_WORKSPACE": str(ws),
            "EVOLVER_REPO_ROOT": str(ws),
            "EVOLVER_NO_PARENT_GIT": "1",
            "MEMORY_DIR": str(ws / "memory"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
            "EVOLVER_HOME": str(ws / ".evomap"),
            "EVOLVER_SETTINGS_DIR": str(ws / ".evolver_settings"),
            "EVOLVER_LOGS_DIR": str(ws / "logs"),
            # pin the window size before the first evolver.config import so the
            # default-wiring assertion cannot be moved by ambient env overrides
            "EVOLVER_GATE_SOAK_MIN_RUNS": "20",
        }
    )


def _gated(i: int, *, flake: bool = False) -> dict[str, Any]:
    """Synthetic EvolutionEvent carrying an acceptance verdict."""
    ev: dict[str, Any] = {
        "id": f"g{i}",
        "timestamp": f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z",
        "outcome": {"status": "success"},
    }
    if flake:
        ev["acceptance_result"] = {"shadow": True, "would_accept": False}
        ev["validation_report"] = {"overall_ok": True}
    else:
        ev["acceptance_result"] = {"shadow": True, "would_accept": True}
    return ev


def _check_rolling_window() -> None:
    from evolver.config import GATE_SOAK_MIN_RUNS
    from evolver.gep.acceptance.report import summarize_acceptance

    # 25 gated events, the single pre-calibration false kill being the OLDEST:
    # the rolling window (default GATE_SOAK_MIN_RUNS) must let it age out.
    aged_out = [_gated(0, flake=True)] + [_gated(i) for i in range(1, 25)]
    m = summarize_acceptance(aged_out)
    assert m["gated_runs"] == 20, f"window must cap at default GATE_SOAK_MIN_RUNS: {m}"
    assert GATE_SOAK_MIN_RUNS == 20, "env pin did not reach config before import"
    assert m["shadow_rejected"] == 0, f"old flake must slide out of the window: {m}"
    assert m["false_kill_risk"] is None, f"no rejections in window -> risk is None: {m}"

    # Same 25 events but the false kill is the NEWEST: it must be counted.
    recent = [_gated(i) for i in range(1, 25)] + [_gated(25, flake=True)]
    m2 = summarize_acceptance(recent)
    assert m2["shadow_rejected"] == 1, f"recent flake must stay in the window: {m2}"
    assert m2["validation_disagreements"] == 1, f"cascade-green rejection counts: {m2}"
    assert m2["false_kill_risk"] == 1.0, f"1 disagreement / 1 rejection: {m2}"


def _check_majority_adjudication() -> None:
    from evolver.gep.acceptance import orchestrator as orch
    from evolver.gep.acceptance.schemas import RepeatObs

    n = 3519
    s_low, s_high, s_third = 3517 / n, 3518 / n, 3516 / n
    here = Path(".")

    def patch(runner: Any) -> tuple[Any, Any]:
        orig = orch._run_t0_repeats
        orch._run_t0_repeats = runner
        return orig, runner

    # Single-test mismatch (1/3519 apart) triggers adjudication; the extra
    # repeat sides with the majority and the minority is trimmed, not hidden.
    obs = [
        RepeatObs(repeat_index=0, score=s_low, denominator=n),
        RepeatObs(repeat_index=1, score=s_high, denominator=n),
    ]
    calls = {"n": 0}

    def fake_repeats(ids: list[str], cwd: Path, *, repeats: int) -> list[RepeatObs]:
        calls["n"] += 1
        return [RepeatObs(repeat_index=99, score=s_high, denominator=n)]

    orig, _ = patch(fake_repeats)
    try:
        kept, info = orch._adjudicate_flakes([], here, obs)
    finally:
        orch._run_t0_repeats = orig
    assert calls["n"] == 1, "exactly one adjudication repeat must run"
    assert [o.score for o in kept] == [s_high, s_high], f"majority value anchored: {kept}"
    assert info is not None and info["trigger"] == "repeat_mismatch", info
    assert info["majority_score"] == round(s_high, 6), info
    assert info["trimmed"] and info["trimmed"][0]["score"] == s_low, (
        f"minority observation recorded in trimmed: {info}"
    )

    # Identical repeats (real regression or real health) never adjudicate.
    consistent = [
        RepeatObs(repeat_index=0, score=1.0, denominator=10),
        RepeatObs(repeat_index=1, score=1.0, denominator=10),
    ]

    def must_not_run(ids: list[str], cwd: Path, *, repeats: int) -> list[RepeatObs]:
        raise AssertionError("consistent repeats must not trigger adjudication")

    orig, _ = patch(must_not_run)
    try:
        kept2, info2 = orch._adjudicate_flakes([], here, consistent)
    finally:
        orch._run_t0_repeats = orig
    assert kept2 == consistent and info2 is None, (kept2, info2)

    # All-distinct (continuous flakiness) keeps everything: fail-toward-reject.
    obs3 = [
        RepeatObs(repeat_index=0, score=s_low, denominator=n),
        RepeatObs(repeat_index=1, score=s_high, denominator=n),
    ]

    def fake_third(ids: list[str], cwd: Path, *, repeats: int) -> list[RepeatObs]:
        return [RepeatObs(repeat_index=98, score=s_third, denominator=n)]

    orig, _ = patch(fake_third)
    try:
        kept3, info3 = orch._adjudicate_flakes([], here, obs3)
    finally:
        orch._run_t0_repeats = orig
    assert len(kept3) == 3, f"no majority -> keep all observations: {kept3}"
    assert info3 is not None and info3["trimmed"] == [], info3


def _check_chunk_retry() -> None:
    from evolver.gep.acceptance import t0_frozen

    here = Path(".")
    orig_run = t0_frozen.subprocess.run

    # First chunk attempt times out, second succeeds -> retry once, count all.
    state = {"calls": 0}

    def flaky_run(*args: Any, **kwargs: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 1:
            raise subprocess.TimeoutExpired("pytest", 1)
        # returncode rides along since round-77: run_pass_rate reads it
        # (rc=4 stale-ID handling) before parsing the summary.
        return SimpleNamespace(stdout="2 passed in 0.01s", returncode=0)

    t0_frozen.subprocess.run = flaky_run
    try:
        result = t0_frozen.run_pass_rate(["tests::a", "tests::b"], here)
    finally:
        t0_frozen.subprocess.run = orig_run
    assert result == (2, 2), f"retried chunk must count its tests: {result}"
    assert state["calls"] == 2, f"exactly one retry: {state}"

    # Both attempts time out -> chunk stays failed (fail-safe zero).
    state2 = {"calls": 0}

    def always_timeout(*args: Any, **kwargs: Any) -> Any:
        state2["calls"] += 1
        raise subprocess.TimeoutExpired("pytest", 1)

    t0_frozen.subprocess.run = always_timeout
    try:
        result2 = t0_frozen.run_pass_rate(["tests::a", "tests::b"], here)
    finally:
        t0_frozen.subprocess.run = orig_run
    assert result2 == (0, 2), f"second failure must keep the chunk at zero: {result2}"
    assert state2["calls"] == 2, f"no third attempt after a second failure: {state2}"


def _check() -> None:
    _check_rolling_window()
    _check_majority_adjudication()
    _check_chunk_retry()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: gate calibration invariant violated: {exc}")
            return 1
        print("PASS: rolling soak window, majority flake adjudication, chunk retry once")
        return 0


if __name__ == "__main__":
    sys.exit(main())
