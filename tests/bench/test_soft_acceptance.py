"""Tests for soft acceptance outcomes (算子即基因 v1.114.0, 支柱一).

Fitness verdicts (drop/flat/regression) are NO LONGER soft-accepted — they
return ``ok=False, outcome=draft_preserved`` and never reach the vault. Only
first-run environment gaps (no_baseline / pack_absent / unmeasured) keep
soft-continuing, and soft-accept never invents a Parent baseline.
"""

from __future__ import annotations

from evolver.bench.frozen_gate import enrich_soft_accept, is_usability_soft_reason


class TestSoftAcceptanceReasons:
    """Only environment gaps are soft; fitness verdicts are honest rejects."""

    def test_no_baseline_is_soft(self) -> None:
        assert is_usability_soft_reason("no_baseline")

    def test_pack_absent_is_soft(self) -> None:
        assert is_usability_soft_reason("pack_absent")

    def test_unmeasured_is_soft(self) -> None:
        assert is_usability_soft_reason("unmeasured")

    def test_drop_is_not_soft(self) -> None:
        """Drop (score below baseline) is an honest reject since v1.114.0."""
        assert not is_usability_soft_reason("drop")

    def test_flat_is_not_soft(self) -> None:
        """Flat (score equal to baseline) is an honest reject since v1.114.0."""
        assert not is_usability_soft_reason("flat")

    def test_regression_is_not_soft(self) -> None:
        """Regression (worse than baseline) is an honest reject since v1.114.0."""
        assert not is_usability_soft_reason("regression")

    def test_non_soft_reasons(self) -> None:
        """Non-soft reasons remain hard blocks."""
        assert not is_usability_soft_reason("gate_error")
        assert not is_usability_soft_reason("seal_violation")
        assert not is_usability_soft_reason("")
        assert not is_usability_soft_reason(None)


class TestEnrichSoftAccept:
    """Soft-accept enrichment only fires for the remaining usability gaps."""

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

    def test_drop_enrichment_is_refused(self) -> None:
        """A drop verdict passed straight in is never minted into an accept:
        ``enrich_soft_accept`` returns it unchanged with accept=False."""
        verdict = {
            "verdict": "reject",
            "reason": "drop",
            "accept": False,
            "score": 0.5,
            "baseline": 0.7,
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["accept"] is False
        assert "soft_accept" not in enriched
        assert enriched["verdict"] == "reject"

    def test_enriched_has_next_steps(self) -> None:
        """Enriched verdicts include next_steps."""
        verdict = {"verdict": "reject", "reason": "no_baseline", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "next_steps" in enriched
        assert isinstance(enriched["next_steps"], list)

    def test_enriched_has_commands(self) -> None:
        """Enriched verdicts include commands."""
        verdict = {"verdict": "reject", "reason": "no_baseline", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "commands" in enriched
        assert isinstance(enriched["commands"], list)

    def test_no_parent_baseline_written(self) -> None:
        """Soft-accept warns that no Parent baseline is written."""
        verdict = {"verdict": "reject", "reason": "no_baseline", "accept": False}
        enriched = enrich_soft_accept(verdict)
        assert "warnings" in enriched
        warning_text = " ".join(enriched["warnings"]).lower()
        assert "does not write a parent baseline" in warning_text

    def test_soft_accept_includes_t0_skipped_warning(self) -> None:
        """Soft-accept with skipped T0 emits t0_skipped_soft warning."""
        verdict = {
            "verdict": "reject",
            "reason": "no_baseline",
            "accept": False,
            "t0": {"mode": "skip", "ok": True},
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["soft_accept"] is True
        warnings_str = " ".join(enriched.get("warnings", []))
        assert "t0_skipped_soft" in warnings_str or "t0_probe=skip" in warnings_str

    def test_soft_accept_includes_t0_minimal_warning(self) -> None:
        """Soft-accept with minimal T0 emits t0_probe warning."""
        verdict = {
            "verdict": "reject",
            "reason": "no_baseline",
            "accept": False,
            "t0": {"mode": "minimal", "ok": True},
        }
        enriched = enrich_soft_accept(verdict)
        assert enriched["soft_accept"] is True
        warnings_str = " ".join(enriched.get("warnings", []))
        assert "t0_probe=minimal" in warnings_str or "t0_skipped_soft" in warnings_str
