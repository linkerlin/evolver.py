"""Anchor probe: telemetry invariants for the meta-report (round-23).

The measurement instrument is now part of the anchor-trigger surface —
three consecutive dogfood rounds fixed telemetry honesty defects
(DEBUG #29 transfer background, #30 ratio populations + failure cost,
#31 monotonic durations). This probe freezes those invariants out-of-tree:
a future mutation that quietly re-opens any of them fails the anchor even
if in-repo tests were weakened alongside it.

The checked functions are pure (no env/file reads at call time), so the
probe isolates the engine env and asserts in-process.
Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


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
        }
    )


def _check() -> None:
    from evolver.gep.solidify import _timing_block
    from evolver.ops.meta_report import build_meta_report

    # --- Invariant 1 (DEBUG #30): ratio sides cover the same population ---
    events = [
        {
            "id": "e1",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["g1"]},
            "signals": ["log_error"],
        },
        {
            "id": "e2",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["g1"]},
            "signals": ["log_error"],
            "validation_timing": {"total_ms": 100_000, "stages": []},
        },
        {
            "id": "e3",
            "outcome": {"status": "failed", "error": "validation_failed"},
            "signals": ["log_error"],
            "validation_timing": {"total_ms": 50_000, "stages": []},
        },
    ]
    eff = build_meta_report(events, [])["panel"]["efficiency"]
    assert eff["validation_ms_per_validated_gain"] == 150_000, eff
    assert eff["timing_coverage"] == {
        "timed_events": 2,
        "timed_accepted": 1,
        "accepted_total": 2,
    }, eff

    # --- Invariant 2 (DEBUG #29): transfer counts only distinctive heads ---
    base = ["autopoiesis:solidify_guard", "autopoiesis:hub_offline_guard"]

    def ev(i: int, extra: list[str]) -> dict[str, object]:
        return {
            "id": f"t{i}",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["g2"]},
            "signals": [*base, *extra],
        }

    # Fixture geometry matters: a head present in half or more of all events
    # is background by the round-18 rule (intentionally conservative). With
    # 5 events, perf_bottleneck (3 of 5) becomes common; log_error (2 of 5)
    # stays distinctive -- exactly the contrast the invariant freezes.
    same = [ev(i, ["perf_bottleneck"]) for i in range(5)]
    assert (
        build_meta_report(same, [])["panel"]["transfer"]["genes_under_multiple_signal_families"]
        == 0
    ), "same distinctive family must not count as transfer"
    diff = [ev(i, ["perf_bottleneck"]) for i in range(3)] + [
        ev(i, ["log_error"]) for i in range(3, 5)
    ]
    assert (
        build_meta_report(diff, [])["panel"]["transfer"]["genes_under_multiple_signal_families"]
        == 1
    ), "differing distinctive heads (background excluded) must count as transfer"

    # --- Invariant 3 (DEBUG #31): durations prefer the monotonic source ---
    block = _timing_block(
        {"duration_ms": 5, "started_at": 100.0, "finished_at": 9_000_100.0, "results": []}
    )
    assert block["total_ms"] == 5, block
    legacy = _timing_block({"started_at": 100.0, "finished_at": 300.0, "results": []})
    assert legacy["total_ms"] == 200, legacy


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: telemetry invariant violated: {exc}")
            return 1
        print("PASS: population-aligned ratios, background-excluded transfer, monotonic durations")
        return 0


if __name__ == "__main__":
    sys.exit(main())
