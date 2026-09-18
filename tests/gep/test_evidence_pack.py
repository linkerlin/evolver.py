"""Tests for evolver.gep.evidence_pack (RSI P1-4, failure-side evidence)."""

from __future__ import annotations

from typing import Any

from evolver.gep.evidence_pack import (
    EVIDENCE_PACK_MAX_CHARS,
    build_evidence_pack,
    render_evidence_pack,
)


def _ok_event(i: int, gene: str = "gene_a") -> dict[str, Any]:
    return {
        "id": f"evt_ok_{i}",
        "gene_id": gene,
        "outcome": {"status": "success"},
        "mutation": {"landed_gene_ids": [gene], "category": "repair"},
        "signals": ["log_error"],
        "diff_snapshot": f"diff --git a/x.py b/x.py\n+edit {i}\n",
    }


def _fail_event(
    i: int, *, signals: list[str] | None = None, added: str | None = None
) -> dict[str, Any]:
    return {
        "id": f"evt_fail_{i}",
        "gene_id": f"gene_f{i}",
        "outcome": {"status": "failed", "error": "validation_failed"},
        "mutation": {"category": "repair"},
        "signals": signals or ["log_error"],
        "novelty_added": added or f"+broken edit {i}\n",
    }


class TestBuildEvidencePack:
    def test_family_matched_by_signal_head(self) -> None:
        events = [_ok_event(1), _fail_event(2, signals=["log_error:snippetA"])]
        pack = build_evidence_pack(events, ["log_error:current"])
        assert len(pack["attempts"]) == 2
        assert pack["family_heads"] == ["log_error"]

    def test_unrelated_families_excluded(self) -> None:
        events = [_ok_event(1), _fail_event(2, signals=["mypy_error"])]
        pack = build_evidence_pack(events, ["log_error"])
        assert [a["event_id"] for a in pack["attempts"]] == ["evt_ok_1"]

    def test_scoreboard_counts(self) -> None:
        events = [_ok_event(1), _fail_event(2), _fail_event(3)]
        pack = build_evidence_pack(events, ["log_error"])
        assert pack["accepted"] == 1
        assert pack["rejected"] == 2

    def test_attempt_rows_carry_gene_and_landed(self) -> None:
        pack = build_evidence_pack([_ok_event(1)], ["log_error"])
        row = pack["attempts"][0]
        assert row["gene_id"] == "gene_a"
        assert row["landed_gene_ids"] == ["gene_a"]
        assert row["status"] == "success"

    def test_rejection_reason_recorded(self) -> None:
        pack = build_evidence_pack([_fail_event(2)], ["log_error"])
        assert "validation_failed" in pack["attempts"][0]["reason"]

    def test_identical_added_lines_share_digest(self) -> None:
        a = build_evidence_pack([_fail_event(1, added="+same\n")], ["log_error"])
        b = build_evidence_pack([_fail_event(2, added="+same\n")], ["log_error"])
        assert a["digests"] == b["digests"]
        assert a["digests"], "failed events with novelty_added must carry a digest"

    def test_distinct_edits_get_distinct_digests(self) -> None:
        pack = build_evidence_pack(
            [_fail_event(1, added="+one\n"), _fail_event(2, added="+two\n")], ["log_error"]
        )
        assert len(set(pack["digests"])) == 2

    def test_digest_deduplicated(self) -> None:
        pack = build_evidence_pack(
            [_fail_event(1, added="+same\n"), _fail_event(2, added="+same\n")], ["log_error"]
        )
        assert pack["digests"] and len(pack["digests"]) == 1

    def test_event_without_editable_text_has_no_digest(self) -> None:
        bare = {
            "id": "evt_bare",
            "outcome": {"status": "failed"},
            "signals": ["log_error"],
        }
        pack = build_evidence_pack([bare], ["log_error"])
        assert pack["digests"] == []

    def test_limit_keeps_most_recent(self) -> None:
        events = [_fail_event(i) for i in range(10)]
        pack = build_evidence_pack(events, ["log_error"], limit=3)
        assert [a["event_id"] for a in pack["attempts"]] == [
            "evt_fail_7",
            "evt_fail_8",
            "evt_fail_9",
        ]

    def test_no_signals_yields_empty(self) -> None:
        pack = build_evidence_pack([_ok_event(1)], [])
        assert pack["attempts"] == []


class TestRenderEvidencePack:
    def test_empty_pack_renders_nothing(self) -> None:
        assert render_evidence_pack({}) == ""
        assert render_evidence_pack(None) == ""
        assert render_evidence_pack(build_evidence_pack([], ["log_error"])) == ""
        assert render_evidence_pack(build_evidence_pack([_ok_event(1)], ["other_family"])) == ""

    def test_header_scoreboard_and_rows_newest_first(self) -> None:
        events = [_ok_event(1), _fail_event(2)]
        rendered = render_evidence_pack(build_evidence_pack(events, ["log_error"]))
        assert "## Evidence Pack" in rendered
        assert "Scoreboard: 2 attempts | 1 accepted | 1 rejected" in rendered
        assert rendered.index("evt_fail_2") < rendered.index("evt_ok_1")

    def test_digest_guard_and_proposal_hint_present(self) -> None:
        rendered = render_evidence_pack(
            build_evidence_pack([_ok_event(1), _fail_event(2)], ["log_error"])
        )
        assert "Already-tried edit fingerprints" in rendered
        assert "swarm_propose" in rendered

    def test_budget_cap_respected_with_counted_omission(self) -> None:
        events = [_fail_event(i, added=f"+edit {i} " + "y" * 150 + "\n") for i in range(60)]
        rendered = render_evidence_pack(build_evidence_pack(events, ["log_error"], limit=60))
        assert len(rendered) <= EVIDENCE_PACK_MAX_CHARS
        assert "omitted for budget" in rendered
        # Newest attempt survives the squeeze; the oldest is the one omitted.
        assert "evt_fail_59" in rendered
        assert "evt_fail_0" not in rendered
