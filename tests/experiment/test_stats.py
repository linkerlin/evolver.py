"""Sprint 24.9: thesis statistics + projection-augmented selector stats."""

from __future__ import annotations

import math

import pytest

from evolver.experiment.stats import (
    achieved_power,
    evaluate_thesis,
    required_n_per_arm,
    two_proportion_z_test,
    wald_ci,
)


class TestTwoProportionZ:
    def test_identical_rates_not_significant(self) -> None:
        result = two_proportion_z_test(15, 50, 15, 50)
        assert result["z"] == pytest.approx(0.0, abs=1e-9)
        assert result["p_value"] == pytest.approx(1.0)

    def test_known_significant_difference(self) -> None:
        # 0.3 vs 0.5 at n=100 each: pooled se=sqrt(0.4*0.6*0.02)≈0.0693,
        # z = 0.2/0.0693 ≈ 2.8868, p ≈ 0.0039.
        result = two_proportion_z_test(30, 100, 50, 100)
        assert result["z"] == pytest.approx(2.8868, abs=1e-3)
        assert result["p_value"] < 0.01

    def test_empty_arm_raises(self) -> None:
        with pytest.raises(ValueError):
            two_proportion_z_test(1, 0, 1, 10)


class TestWaldCI:
    def test_ci_excludes_zero_for_big_gap(self) -> None:
        # delta=0.30, se=sqrt(0.09+0.24)/100 ≈ 0.05745, width≈2·1.96·se≈0.2252.
        ci = wald_ci(10, 100, 40, 100)
        assert ci[0] > 0.0  # p_b - p_a clearly positive
        lo, hi = ci
        assert hi - lo == pytest.approx(0.2252, abs=0.01)

    def test_ci_covers_observed_delta(self) -> None:
        for sa, na, sb, nb in ((5, 40, 12, 45), (20, 60, 18, 65)):
            lo, hi = wald_ci(sa, na, sb, nb)
            observed = sb / nb - sa / na
            assert lo <= observed <= hi


class TestPowerAndN:
    def test_achieved_power_grows_with_effect(self) -> None:
        small = achieved_power(45, 100, 55, 100)  # delta 0.10
        large = achieved_power(30, 100, 70, 100)  # delta 0.40
        assert large > small
        assert achieved_power(50, 100, 50, 100) == 0.0

    def test_required_n_shrinks_as_effect_grows(self) -> None:
        n_small = required_n_per_arm(0.30, 0.35)
        n_large = required_n_per_arm(0.30, 0.50)
        assert n_large < n_small
        # Classic 0.30→0.50 at alpha=.05, power=.80 lands in the low hundreds.
        assert 100 <= n_small <= 3000
        assert math.ceil(n_large) >= 2

    def test_zero_effect_raises(self) -> None:
        with pytest.raises(ValueError):
            required_n_per_arm(0.4, 0.4)


class TestEvaluateThesis:
    def test_insufficient_samples_gate(self) -> None:
        verdict = evaluate_thesis(9, 10, 10, 10)  # big gap but tiny n
        assert verdict["verdict"] == "insufficient_samples"
        assert verdict["significant"] is False

    def test_clear_improvement(self) -> None:
        verdict = evaluate_thesis(30, 100, 55, 100)  # +0.25, p << alpha, n >= 30
        assert verdict["verdict"] == "evolved_better"
        assert verdict["significant"]
        assert verdict["ci95"][0] > 0

    def test_regression_detected(self) -> None:
        verdict = evaluate_thesis(55, 100, 30, 100)
        assert verdict["verdict"] == "worse"

    def test_practical_delta_gate(self) -> None:
        # +0.02 with n=5000 → significant but below min_delta.
        verdict = evaluate_thesis(1500, 5000, 1600, 5000)
        assert verdict["verdict"] == "no_clear_improvement"
