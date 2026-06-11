"""Tests for evolver.evolve.pipeline.enrich."""

from __future__ import annotations

from evolver.evolve.pipeline.enrich import enrich_phase


class TestEnrichPhase:
    async def test_basic(self):
        ctx = {"signals": ["s1"], "genes": ["g1"], "capsules": ["c1"]}
        result = await enrich_phase(ctx)
        assert result["observations"]["signals_count"] == 1
        assert result["observations"]["genes_count"] == 1

    async def test_plateau_required(self):
        ctx = {"signals": ["plateau_pivot_required"], "genes": [], "capsules": []}
        result = await enrich_phase(ctx)
        assert result["IS_RANDOM_DRIFT"] is True
        assert result["plateau_override"]["severity"] == "required"

    async def test_plateau_suggested(self):
        ctx = {"signals": ["plateau_pivot_suggested"], "genes": [], "capsules": []}
        result = await enrich_phase(ctx)
        assert result["plateau_override"]["severity"] == "suggested"
