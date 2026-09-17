"""Anchor probe: acceptance-gate verdict reachability (round-30).

The soak phase metric ``gated_runs`` is a rolling-window count whose ceiling
is ``GATE_SOAK_MIN_RUNS``: once the window filled, the number froze at 20 and
could no longer express progress — and every hand-written 回执 read from it
drifted. Worse, with zero human-confirmed true positives the old
``under_intercepting`` branch made ``ready`` structurally unreachable: after
the pre-calibration false kills aged out, a healthy quiet window produced
another non-ready verdict forever.

This probe freezes the round-30 correction out-of-tree (演进方案.md §11.4 P0-1):

- ``gated_cumulative`` counts every gated event, independent of the window;
- promotion requires >= 1 human-confirmed true positive, and that
  confirmation must survive sliding out of the window;
- a quiet window *with* confirmation reads ``collecting_verified`` — never
  ``under_intercepting`` (dead end) and never ``ready`` (no evidence yet).

Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
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
            # pin the window size before the first evolver.config import
            "EVOLVER_GATE_SOAK_MIN_RUNS": "20",
        }
    )


def _gated(i: int) -> dict[str, Any]:
    """Synthetic EvolutionEvent carrying an accepting gate verdict."""
    return {
        "id": f"evt_{i}",
        "timestamp": f"2026-10-{i + 1:02d}T00:00:00Z",
        "acceptance_result": {"reason": "t0_only_no_regression"},
    }


def _check_cumulative_counter() -> None:
    from evolver.config import GATE_SOAK_MIN_RUNS
    from evolver.gep.acceptance.report import summarize_acceptance

    assert GATE_SOAK_MIN_RUNS == 20, "env pin did not reach config before import"
    m = summarize_acceptance([_gated(i) for i in range(28)])
    assert m["gated_runs"] == 20, f"window must still cap: {m}"
    assert m["gated_cumulative"] == 28, f"cumulative counts every gated event: {m}"
    assert m["gated_cumulative"] > m["gated_runs"], "saturation must stay visible"


def _check_confirmation_floor() -> None:
    from evolver.gep.acceptance.report import gate_soak_recommendation, summarize_acceptance

    events = [_gated(i) for i in range(25)]
    quiet = summarize_acceptance(events)
    assert quiet["shadow_rejected"] == 0, f"fixture must be a quiet window: {quiet}"

    verdict = gate_soak_recommendation(quiet)
    assert verdict["verdict"] == "unverified", f"unadjudicated quiet window: {verdict}"

    confirmed = summarize_acceptance(events, verified={"evt_0": "true_positive"})
    verdict2 = gate_soak_recommendation(confirmed)
    assert verdict2["verdict"] == "collecting_verified", f"dead end persists: {verdict2}"
    assert verdict2["verdict"] not in {"ready", "under_intercepting"}, verdict2


def _check_confirmation_survives_age_out() -> None:
    from evolver.gep.acceptance.report import gate_soak_recommendation, summarize_acceptance

    oldest = dict(_gated(0), id="evt_confirmed", timestamp="2026-01-01T00:00:00Z")
    events: list[dict[str, Any]] = [oldest] + [_gated(i) for i in range(1, 25)]
    m = summarize_acceptance(events, verified={"evt_confirmed": "true_positive"})
    assert "evt_confirmed" not in [e.get("id") for e in events[-20:]], (
        "fixture: confirmation must be aged out of the window"
    )
    assert m["verified_true_positives"] == 1, f"all-time counting broken: {m}"
    assert gate_soak_recommendation(m)["verdict"] == "collecting_verified"


def _check() -> None:
    _check_cumulative_counter()
    _check_confirmation_floor()
    _check_confirmation_survives_age_out()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: gate verdict reachability violated: {exc}")
            return 1
    print("PASS: cumulative counter, confirmation floor, age-out survival")
    return 0


if __name__ == "__main__":
    sys.exit(main())
