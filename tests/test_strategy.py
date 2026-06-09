"""Tests for evolver.gep.strategy — equivalent to evolver/test/strategy.test.js."""

from __future__ import annotations

import pytest

from evolver.gep import strategy


def test_strategy_names() -> None:
    names = strategy.get_strategy_names()
    for expected in ("balanced", "innovate", "harden", "repair-only", "early-stabilize", "steady-state"):
        assert expected in names


def test_strategies_sum_to_one() -> None:
    for name, s in strategy.STRATEGIES.items():
        total = s.repair + s.optimize + s.innovate + (s.explore or 0)
        assert abs(total - 1.0) < 0.01, f"{name} sums to {total}"


def test_resolve_strategy_default() -> None:
    s = strategy.resolve_strategy({})
    assert s.name in ("balanced", "early-stabilize")


def test_resolve_strategy_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVE_STRATEGY", "harden")
    s = strategy.resolve_strategy({})
    assert s.name == "harden"
    assert s.label == "Hardening"


def test_resolve_strategy_force_innovation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_INNOVATION", "true")
    s = strategy.resolve_strategy({})
    assert s.name == "innovate"


def test_resolve_strategy_saturation_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVE_STRATEGY", raising=False)
    s = strategy.resolve_strategy({"signals": ["evolution_saturation"]})
    assert s.name == "steady-state"


def test_resolve_strategy_explicit_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVE_STRATEGY", "harden")
    monkeypatch.setenv("FORCE_INNOVATION", "true")
    s = strategy.resolve_strategy({})
    assert s.name == "harden"


def test_resolve_strategy_unknown_fallback() -> None:
    s = strategy.resolve_strategy({"signals": ["force_steady_state"]})
    assert s.name == "steady-state"
