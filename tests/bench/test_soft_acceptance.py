"""Tests for soft acceptance outcomes (Task 3: drop/flat/regression/unmeasured).

Covers soft-default UX (2026-10-31): all former hard acceptance failures now
soft-accept with warnings, experience written, no Parent baseline invented.
"""

from __future__ import annotations

import pytest

from evolver.bench.frozen_gate import enrich_soft_accept, is_usability_soft_reason


class TestSoftAcceptanceReasons:
    """Test that all specified reasons are recognized as soft-accept eligible."""

    def test_no_baseline_is_soft(self) -> None:
        assert is_usability_soft_reason("no_baseline")

    def test_pack_absent_is_soft(self) -> None:
        assert is_usability_soft_reason("pack_absent")

    def test_unmeasured_is_soft(self) -> None:
        assert is_usability_soft_reason("unmeasured")

    def test_drop_is_soft(self) -> None:
        """Drop (score below baseline) is now soft-accept."""
        assert is_usability_soft_reason("drop")

    def test_flat_is_soft(self) -> None:
        """Flat (score equal to baseline) is now soft-accept."""
        assert is_usability_soft_reason("flat")

    def test_regression_is_soft(self) -> None:
        """Regression (worse than baseline) is now soft-accept."""
        assert is_usability_soft_reason("regression")

    def test_non_soft_reasons(self) -> None:
        """Non-soft reasons remain hard blocks."""
        assert not is_usability_soft_reason("gate_error")
        assert not is_usability_soft_reason("seal_violation")
        assert not is_usability_soft_reason("")
        assert not is_usability_soft_reason(None)


class TestEnrichSoftAccept:
    """Test soft-accept enrichment for all soft reasons."""

    def test_drop_enriched(self) -> None:
        """Drop verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "drop",
            "accept": False,
            "score": 0.5,
            "baseline": 0.7,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["verdict"] == "soft_accept"
        assert enriched["soft_reason"] == "drop"
        assert "warnings" in enriched
        assert len(enriched["warnings"]) > 0

    def test_flat_enriched(self) -> None:
        """Flat verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "flat",
            "accept": False,
            "score": 0.7,
            "baseline": 0.7,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["soft_reason"] == "flat"

    def test_regression_enriched(self) -> None:
        """Regression verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "regression",
            "accept": False,
            "score": 0.6,
            "baseline": 0.8,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["soft_reason"] == "regression"

    def test_unmeasured_enriched(self) -> None:
        """Unmeasured verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "unmeasured",
            "accept": False,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["soft_reason"] == "unmeasured"

    def test_no_baseline_enriched(self) -> None:
        """No baseline verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "no_baseline",
            "accept": False,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["soft_reason"] == "no_baseline"

    def test_pack_absent_enriched(self) -> None:
        """Pack absent verdict becomes soft-accept with warnings."""
        verdict = {
            "verdict": "reject",
            "reason": "pack_absent",
            "accept": False,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is True
        assert enriched["soft_accept"] is True
        assert enriched["soft_reason"] == "pack_absent"

    def test_enriched_has_next_steps(self) -> None:
        """Enriched verdicts include next_steps."""
        verdict = {"verdict": "reject", "reason": "drop", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "next_steps" in enriched
        assert isinstance(enriched["next_steps"], list)

    def test_enriched_has_commands(self) -> None:
        """Enriched verdicts include commands."""
        verdict = {"verdict": "reject", "reason": "drop", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "commands" in enriched
        assert isinstance(enriched["commands"], list)

    def test_no_parent_baseline_written(self) -> None:
        """Soft-accept warns that no Parent baseline is written."""
        verdict = {"verdict": "reject", "reason": "drop", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "warnings" in enriched
        warning_text = " ".join(enriched["warnings"]).lower()
        assert "does not write a parent baseline" in warning_text
