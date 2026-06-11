"""Tests for evolver.gep.idle_scheduler."""

from unittest.mock import patch

import pytest

from evolver.gep.idle_scheduler import (
    INTENSITY_DEEP_THRESHOLD,
    INTENSITY_LIGHT_THRESHOLD,
    INTENSITY_NORMAL_THRESHOLD,
    EvolutionIntensity,
    get_intensity,
    intensity_for_duration,
    should_mutate,
)


class TestIntensityForDuration:
    def test_active(self):
        assert intensity_for_duration(0) == EvolutionIntensity.signal_only
        assert intensity_for_duration(30) == EvolutionIntensity.signal_only

    def test_light(self):
        assert intensity_for_duration(INTENSITY_LIGHT_THRESHOLD) == EvolutionIntensity.light
        assert intensity_for_duration(INTENSITY_LIGHT_THRESHOLD + 1) == EvolutionIntensity.light

    def test_normal(self):
        assert intensity_for_duration(INTENSITY_NORMAL_THRESHOLD) == EvolutionIntensity.normal

    def test_deep(self):
        assert intensity_for_duration(INTENSITY_DEEP_THRESHOLD) == EvolutionIntensity.deep
        assert intensity_for_duration(INTENSITY_DEEP_THRESHOLD + 100) == EvolutionIntensity.deep


class TestShouldMutate:
    def test_signal_only_no_mutate(self):
        with patch("evolver.gep.idle_scheduler._idle_time", return_value=0):
            assert not should_mutate()

    def test_light_allows_mutate(self):
        with patch("evolver.gep.idle_scheduler._idle_time", return_value=INTENSITY_LIGHT_THRESHOLD):
            assert should_mutate()


class TestGetIntensity:
    def test_returns_enum(self):
        with patch("evolver.gep.idle_scheduler._idle_time", return_value=0):
            intensity = get_intensity()
            assert isinstance(intensity, EvolutionIntensity)
