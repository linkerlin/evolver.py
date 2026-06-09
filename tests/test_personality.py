"""Tests for evolver.gep.personality."""

from __future__ import annotations

import pytest

from evolver.gep import personality as pers


def test_load_personality_defaults() -> None:
    p = pers.load_personality()
    assert p["rigor"] == 0.5
    assert p["creativity"] == 0.5
    assert p["risk_tolerance"] == 0.3


def test_save_and_load_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_SETTINGS_DIR", str(tmp_path))
    pers.save_personality({"rigor": 0.8, "creativity": 0.2, "risk_tolerance": 0.1})
    p = pers.load_personality()
    assert p["rigor"] == 0.8
    assert p["creativity"] == 0.2
    assert p["risk_tolerance"] == 0.1


def test_save_clamps_values(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_SETTINGS_DIR", str(tmp_path))
    pers.save_personality({"rigor": 1.5, "creativity": -0.3, "risk_tolerance": 0.5})
    p = pers.load_personality()
    assert p["rigor"] == 1.0
    assert p["creativity"] == 0.0


def test_adapt_personality_success_streak() -> None:
    events = [
        {"outcome": {"status": "success"}, "mutation": {"category": "innovate"}}
        for _ in range(5)
    ]
    p = pers.adapt_personality(pers.DEFAULT_PERSONALITY.copy(), recent_events=events)
    assert p["creativity"] > pers.DEFAULT_PERSONALITY["creativity"]
    assert p["risk_tolerance"] > pers.DEFAULT_PERSONALITY["risk_tolerance"]


def test_adapt_personality_failure_streak() -> None:
    events = [
        {"outcome": {"status": "failed"}, "mutation": {"category": "repair"}}
        for _ in range(5)
    ]
    p = pers.adapt_personality(pers.DEFAULT_PERSONALITY.copy(), recent_events=events)
    assert p["rigor"] > pers.DEFAULT_PERSONALITY["rigor"]
    assert p["risk_tolerance"] < pers.DEFAULT_PERSONALITY["risk_tolerance"]


def test_adapt_personality_empty_events() -> None:
    p = pers.adapt_personality(pers.DEFAULT_PERSONALITY.copy(), recent_events=[])
    assert p == pers.DEFAULT_PERSONALITY


def test_personality_to_strategy_bias() -> None:
    bias = pers.personality_to_strategy_bias({"rigor": 0.9, "creativity": 0.1, "risk_tolerance": 0.1})
    assert bias["repair"] > bias["innovate"]
    assert abs(bias["repair"] + bias["optimize"] + bias["innovate"] - 1.0) < 0.01


def test_is_high_risk_personality() -> None:
    assert pers.is_high_risk_personality({"rigor": 0.3, "creativity": 0.5, "risk_tolerance": 0.7}) is True
    assert pers.is_high_risk_personality({"rigor": 0.8, "creativity": 0.5, "risk_tolerance": 0.2}) is False


def test_is_conservative_personality() -> None:
    assert pers.is_conservative_personality({"rigor": 0.8, "creativity": 0.5, "risk_tolerance": 0.2}) is True
    assert pers.is_conservative_personality({"rigor": 0.5, "creativity": 0.5, "risk_tolerance": 0.5}) is False
