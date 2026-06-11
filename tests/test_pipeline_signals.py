"""Tests for evolver.evolve.pipeline.signals."""

from __future__ import annotations

from evolver.evolve.pipeline.signals import should_skip_hub_calls


class TestShouldSkipHubCalls:
    def test_empty(self):
        assert should_skip_hub_calls([]) is False

    def test_actionable(self):
        assert should_skip_hub_calls(["log_error"]) is False

    def test_saturation_only(self):
        assert should_skip_hub_calls(["evolution_saturation"]) is True

    def test_mixed(self):
        assert should_skip_hub_calls(["evolution_saturation", "log_error"]) is False

    def test_errsig(self):
        assert should_skip_hub_calls(["errsig:something"]) is False

    def test_long_sig(self):
        assert should_skip_hub_calls(["this_is_a_very_long_signal_name"]) is False
