"""Meta-report library panel — RSI P1-5 retrieval quality (read-only)."""

from __future__ import annotations

from typing import Any

from evolver.ops.meta_report import build_meta_report


def _events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(3):
        events.append(
            {
                "id": f"evt_land_{i}",
                "outcome": {"status": "success"},
                "mutation": {"landed_gene_ids": ["gene_dead"]},
                "signals": ["log_error"],
            }
        )
        events.append(
            {"id": f"evt_fail_{i}", "outcome": {"status": "failed"}, "signals": ["log_error"]}
        )
    events.extend(
        {"id": f"evt_ok_{i}", "outcome": {"status": "success"}, "signals": ["hub_offline"]}
        for i in range(5)
    )
    return events


def test_library_panel_reports_retrieval_quality() -> None:
    report = build_meta_report(_events(), [])
    library = report["panel"]["library"]
    assert library["landed_genes"] == 1
    assert library["landings_tracked"] == 3
    assert library["evaluable_landings"] == 3
    assert library["resolution_rate"] == 0.0
    assert library["zero_work_candidates"] == ["gene_dead"]
    assert library["lifecycle"] == {"active": 1, "under_review": 0, "retired": 0}


def test_library_panel_accepts_lifecycle_status_map() -> None:
    report = build_meta_report(_events(), [], {"gene_dead": "retired"})
    lifecycle = report["panel"]["library"]["lifecycle"]
    assert lifecycle == {"active": 0, "under_review": 0, "retired": 1}


def test_library_panel_backwards_compatible() -> None:
    # Existing callers pass two args; absent lifecycle counts everything active.
    report = build_meta_report(_events())
    assert report["panel"]["library"]["lifecycle"]["active"] == 1


def test_library_panel_counts_resolved_rate() -> None:
    events = [
        {
            "id": "ok",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["gene_good"]},
            "signals": ["log_error"],
        },
        *[
            {"id": f"pad_{i}", "outcome": {"status": "success"}, "signals": ["hub_offline"]}
            for i in range(5)
        ],
    ]
    library = build_meta_report(events, [])["panel"]["library"]
    assert library["resolution_rate"] == 1.0
    assert library["zero_work_candidates"] == []
