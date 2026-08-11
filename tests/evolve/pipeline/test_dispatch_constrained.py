"""Tests for dispatch constrained-hook anchoring (Sprint C1)."""

from __future__ import annotations

import asyncio

import pytest

from evolver.evolve.pipeline.dispatch import dispatch_phase


def _ctx(gene: dict) -> dict:
    return {
        "cycle_id": "c1",
        "run_id": "r1",
        "signals": ["log_error"],
        "selected_gene": gene,
        "mutation": {"id": "m1", "validation": []},
        "skip_hub_calls": True,
        "scan_time_iso": "2026-01-01T00:00:00Z",
    }


_CONSTRAINED = {
    "id": "g1",
    "mechanism_family": "prompt_instruction",
    "target_hook": "build_gep_prompt",
}


class TestDispatchConstrainedHook:
    def test_flag_off_no_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CONSTRAINED_GENES", "0")
        result = asyncio.run(dispatch_phase(_ctx(_CONSTRAINED)))
        assert "constrained_hook_block" not in result

    def test_flag_on_anchors_constraint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CONSTRAINED_GENES", "1")
        result = asyncio.run(dispatch_phase(_ctx(_CONSTRAINED)))
        block = result["constrained_hook_block"]
        assert "CONSTRAINED EDIT MODE" in block
        assert "prompt_instruction" in block
        assert "build_gep_prompt" in block
        assert "ONLY editable hook" in block

    def test_gene_without_constraint_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CONSTRAINED_GENES", "1")
        result = asyncio.run(dispatch_phase(_ctx({"id": "g_plain"})))
        assert "constrained_hook_block" not in result

    def test_unknown_family_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CONSTRAINED_GENES", "1")
        result = asyncio.run(
            dispatch_phase(_ctx({"id": "g2", "mechanism_family": "bogus", "target_hook": "x"}))
        )
        assert "constrained_hook_block" not in result

    def test_hook_not_in_family_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CONSTRAINED_GENES", "1")
        result = asyncio.run(
            dispatch_phase(
                _ctx(
                    {
                        "id": "g3",
                        "mechanism_family": "gene_library",
                        "target_hook": "build_gep_prompt",  # wrong family
                    }
                )
            )
        )
        assert "constrained_hook_block" not in result
