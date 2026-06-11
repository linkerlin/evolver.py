"""Tests for evolver.evolve.pipeline.hub."""

from __future__ import annotations

from evolver.evolve.pipeline.hub import hub_phase


class TestHubPhase:
    async def test_skip(self):
        ctx = {"skip_hub_calls": True}
        result = await hub_phase(ctx)
        assert result["hub_hit"]["reason"] == "idle_skip"

    async def test_offline(self, monkeypatch):
        async def fail(*a, **k):
            raise Exception("no network")

        monkeypatch.setattr("evolver.gep.a2a_protocol.fetch_tasks", fail)
        ctx = {}
        result = await hub_phase(ctx)
        assert result["hub_hit"]["reason"] == "offline"
