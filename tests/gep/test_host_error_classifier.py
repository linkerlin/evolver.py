"""Tests for evolver.gep.host_error_classifier (#571).

Port of ``evolver/test/hostClientErrorSignals.test.js``. An unrecoverable
host/LLM 4xx error must NOT be attributed to a Gene: it must not feed the
consecutive-failure streak or ban_gene / failure_loop_detected, and must
surface the actionable ``host_llm_client_error`` signal instead.
"""

from __future__ import annotations

from evolver.gep import signals as sig
from evolver.gep.host_error_classifier import (
    HOST_PROVIDER_ERR_RE,
    is_host_client_error,
)


def _failed_streak(gene_id: str) -> list[dict]:
    """Five failed, non-empty cycles on one gene — trips ban/loop on its own."""
    return [
        {
            "intent": "innovate",
            "signals": [],
            "genes_used": [gene_id],
            "blast_radius": {"files": 1, "lines": 5},
            "outcome": {"status": "failed", "score": 0.2},
        }
        for _ in range(5)
    ]


def test_matches_host_llm_4xx_provider_errors() -> None:
    assert is_host_client_error("[LLM ERROR] field MaxTokens invalid, should be in [1, 65536]")
    assert is_host_client_error("provider returned invalid_api_key")
    assert is_host_client_error("insufficient_quota for this request")
    assert is_host_client_error("Request failed with HTTP 400")
    assert is_host_client_error("status code: 401")
    assert is_host_client_error("got 403 Forbidden from the gateway")
    assert is_host_client_error("rate limit exceeded, retry later")


def test_does_not_match_ordinary_gene_or_test_failures() -> None:
    assert not is_host_client_error("AssertionError: expected 2 to equal 3")
    # A bare number must not collide: "400 lines" is not an HTTP 400.
    assert not is_host_client_error("refactor touched 400 lines across 12 files")
    assert not is_host_client_error("TypeError: cannot read property foo of undefined")
    assert not is_host_client_error("")
    assert not is_host_client_error(None)  # type: ignore[arg-type]


def test_regex_is_stateless_repeated_calls_agree() -> None:
    # Python has no global flag; re.search carries no lastIndex, so two calls
    # in a row must agree (the Node contract's statelessness intent).
    assert is_host_client_error("HTTP 400")
    assert is_host_client_error("HTTP 400")
    assert HOST_PROVIDER_ERR_RE.search("HTTP 400") is not None


def test_host_4xx_streak_surfaces_host_signal_and_suppresses_ban_loop() -> None:
    signals = sig.extract_signals(
        recent_session_transcript=(
            "**ASSISTANT**: [LLM ERROR] field MaxTokens invalid, should be in [1, 65536]"
        ),
        today_log="",
        memory_snippet="",
        user_snippet="",
        recent_events=_failed_streak("gene_x"),
    )
    assert "host_llm_client_error" in signals
    assert "failure_loop_detected" not in signals
    assert not any(s.startswith("ban_gene:") for s in signals)
    assert not any(s.startswith("consecutive_failure_streak_") for s in signals)
    assert "force_innovation_after_repair_loop" not in signals


def test_genuine_gene_failure_streak_still_bans() -> None:
    # Regression guard: a real gene/test failure must still be attributed.
    transcript = "**ASSISTANT**: AssertionError: expected solidify to write 1 file"
    signals = sig.extract_signals(
        recent_session_transcript=transcript,
        today_log="",
        memory_snippet="",
        user_snippet="",
        recent_events=_failed_streak("gene_x"),
    )
    assert "failure_loop_detected" in signals
    assert "ban_gene:gene_x" in signals
    assert "host_llm_client_error" not in signals
