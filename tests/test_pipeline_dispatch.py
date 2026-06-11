"""Tests for evolver.evolve.pipeline.dispatch."""

from __future__ import annotations

import pytest

from evolver.evolve.pipeline.dispatch import _format_preview


class TestFormatPreview:
    def test_basic(self):
        out = _format_preview([{"id": "g1"}])
        assert "g1" in out
        assert "```json" in out
