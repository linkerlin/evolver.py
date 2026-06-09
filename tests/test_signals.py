"""Tests for evolver.gep.signals — equivalent to evolver/test/signals.test.js."""

from __future__ import annotations

import pytest

from evolver.gep import signals as sig


def test_has_opportunity_signal_detects_base_names() -> None:
    assert sig.has_opportunity_signal(["user_feature_request"]) is True
    assert sig.has_opportunity_signal(["user_feature_request:add dark mode"]) is True
    assert sig.has_opportunity_signal(["log_error"]) is False


def test_analyze_recent_history_empty() -> None:
    h = sig.analyze_recent_history(None)
    assert h["suppressedSignals"] == set()
    assert h["recentIntents"] == []


def test_analyze_recent_history_suppresses_over_processed() -> None:
    events = [{"signals": ["log_error"], "intent": "repair"} for _ in range(3)]
    h = sig.analyze_recent_history(events)
    assert "log_error" in h["suppressedSignals"]


def test_extract_keyword_score_perf_bottleneck() -> None:
    scored = sig._extract_keyword_score("the system is very slow and has high memory usage timeout")
    assert "perf_bottleneck" in scored


def test_extract_regex_error_hit() -> None:
    s = sig._extract_regex("Something went wrong: Error: connection refused", "something went wrong: error: connection refused", True)
    assert "log_error" in s
    assert any(x.startswith("errsig:") for x in s)


def test_extract_regex_feature_request_multilingual() -> None:
    s = sig._extract_regex("Please add a dark mode", "please add a dark mode", False)
    assert "user_feature_request" in s
    assert any(x.startswith("user_feature_request:") for x in s)


def test_extract_signals_returns_stable_default() -> None:
    s = sig.extract_signals(recent_session_transcript="", today_log="", memory_snippet="", user_snippet="")
    assert "stable_success_plateau" in s


def test_extract_signals_detects_error() -> None:
    s = sig.extract_signals(recent_session_transcript="Error: connection refused")
    assert "log_error" in s


def test_extract_signals_repair_loop() -> None:
    events = [{"signals": ["log_error"], "intent": "repair", "outcome": {"status": "failed"}} for _ in range(4)]
    s = sig.extract_signals(recent_session_transcript="Error", recent_events=events)
    assert "repair_loop_detected" in s
    assert "force_innovation_after_repair_loop" in s


def test_should_skip_hub_calls_only_saturation() -> None:
    assert sig.should_skip_hub_calls(["evolution_saturation", "force_steady_state"]) is True


def test_should_skip_hub_calls_actionable() -> None:
    assert sig.should_skip_hub_calls(["evolution_saturation", "log_error"]) is False
