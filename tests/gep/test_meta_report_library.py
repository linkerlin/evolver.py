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


class TestFaithfulUse:
    """Round-38 (RSI P1-3 prerequisite): retrieval vs faithful following."""

    def _land(self, i: int, gene: str = "gene_x") -> dict[str, Any]:
        return {
            "id": f"evt_land_{i}",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": [gene]},
            "signals": ["log_error"],
            "diff_snapshot": f"diff --git a/f{i} b/f{i}\n+line {i}\n",
        }

    def _reuse(self, i: int, gene: str, diff: str) -> dict[str, Any]:
        return {
            "id": f"evt_reuse_{i}",
            "gene_id": gene,
            "outcome": {"status": "success"},
            "signals": ["log_error"],
            "diff_snapshot": diff,
        }

    def test_novel_reuse_counts_faithful(self) -> None:
        events = [
            self._land(0),
            self._reuse(1, "gene_x", "diff --git a/g b/g\n+novel edit\n"),
        ]
        fu = build_meta_report(events, [])["panel"]["library"]["faithful_use"]
        assert fu["reused_genes"] == 1
        assert fu["retrieval_rate"] == 1.0
        assert fu["reuse_events"] == 1
        assert fu["novel_edits"] == 1
        assert fu["faithful_use_rate"] == 1.0

    def test_repeated_digest_reuse_is_not_faithful(self) -> None:
        # RQGM shape: the executor re-applies the SAME edit under the same
        # gene — the evidence-pack "do NOT repeat" contract violated.
        same = "diff --git a/g b/g\n+identical edit\n"
        events = [
            self._land(0),
            self._reuse(1, "gene_x", "diff --git a/one b/one\n+first\n"),
            self._reuse(2, "gene_x", same),
            self._reuse(3, "gene_x", same),
        ]
        fu = build_meta_report(events, [])["panel"]["library"]["faithful_use"]
        assert fu["reuse_events"] == 3
        assert fu["novel_edits"] == 2
        assert fu["faithful_use_rate"] == round(2 / 3, 3)

    def test_reuse_without_editable_text_not_counted_faithful(self) -> None:
        events = [self._land(0), self._reuse(1, "gene_x", "")]
        fu = build_meta_report(events, [])["panel"]["library"]["faithful_use"]
        assert fu["reuse_events"] == 1
        assert fu["novel_edits"] == 0
        assert fu["faithful_use_rate"] == 0.0

    def test_no_landed_genes_gives_none_rates(self) -> None:
        events = [{"id": "e", "outcome": {"status": "success"}, "signals": ["s"]}]
        fu = build_meta_report(events, [])["panel"]["library"]["faithful_use"]
        assert fu["reused_genes"] == 0
        assert fu["retrieval_rate"] is None
        assert fu["faithful_use_rate"] is None


class TestCostPanel:
    """Round-38 (RSI P1-3 prerequisite): validation cost accounting."""

    def test_cost_over_timed_population(self) -> None:
        events = [
            {
                "id": "a",
                "outcome": {"status": "success"},
                "signals": ["s"],
                "validation_timing": {"total_ms": 100_000, "stages": []},
            },
            {
                "id": "b",
                "outcome": {"status": "failed"},
                "signals": ["s"],
                "validation_timing": {"total_ms": 200_000, "stages": []},
            },
            {
                "id": "c",
                "outcome": {"status": "success"},
                "signals": ["s"],
                "validation_timing": {"total_ms": 300_000, "stages": []},
            },
            # untimed event must not dilute either side
            {"id": "d", "outcome": {"status": "success"}, "signals": ["s"]},
        ]
        cost = build_meta_report(events, [])["panel"]["cost"]
        assert cost["timed_events"] == 3
        assert cost["median_ms_per_event"] == 200_000
        assert cost["mean_ms_per_event"] == 200_000
        assert cost["total_engine_ms"] == 600_000
        assert cost["rejection_ms_share"] == round(200_000 / 600_000, 3)
        assert cost["k2_extra_ms_per_cycle"] == 200_000

    def test_cost_empty_population(self) -> None:
        cost = build_meta_report([], [])["panel"]["cost"]
        assert cost["timed_events"] == 0
        assert cost["median_ms_per_event"] is None
        assert cost["rejection_ms_share"] is None
        assert cost["k2_extra_ms_per_cycle"] is None


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
