"""Tests for evolver.gep.self_pr."""

import pytest
from unittest.mock import patch

from evolver.gep.self_pr import (
    DEFAULT_MIN_SCORE,
    SelfPRResult,
    _check_cooldown,
    _check_diff_dedup,
    _check_policy,
    _check_score,
    _check_secrets,
    _diff_similarity,
    create_self_pr,
)


class TestChecks:
    def test_score_pass(self):
        assert _check_score(0.9, DEFAULT_MIN_SCORE)

    def test_score_fail(self):
        assert not _check_score(0.5, DEFAULT_MIN_SCORE)

    def test_policy_pass(self):
        assert _check_policy("diff --git a/foo.py b/foo.py\n+hello")

    def test_policy_fail(self):
        assert not _check_policy("diff --git a/.env b/.env\n+secret")

    def test_secrets_pass(self):
        assert _check_secrets("some normal code")

    def test_secrets_fail(self):
        assert not _check_secrets("Authorization: Bearer sk-1234567890abcdefghij")

    def test_cooldown(self):
        import time
        registry = {
            "prs": [
                {"gene_id": "g1", "created_at": time.time()},
            ]
        }
        assert not _check_cooldown("g1", registry)
        assert _check_cooldown("g2", registry)

    def test_diff_dedup(self):
        diff = "+line1\n+line2"
        registry = {
            "prs": [
                {"diff_text": "+line1\n+line2"},
            ]
        }
        assert not _check_diff_dedup(diff, registry)

    def test_diff_similarity(self):
        a = "+line1\n+line2\n+line3"
        b = "+line1\n+line2\n+line4"
        sim = _diff_similarity(a, b)
        assert 0 < sim < 1


class TestCreateSelfPR:
    def test_feature_flag_off(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "0")
        result = create_self_pr(
            diff_text="+hello",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        assert "feature flag" in result.reason.lower()

    def test_low_confidence(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="+hello",
            gene_id="g1",
            gene_summary="test",
            confidence=0.5,
        )
        assert not result.success
        assert "confidence" in result.reason.lower()

    def test_policy_failure(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="diff --git a/.env b/.env\n+secret=1",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        assert "policy" in result.reason.lower()

    def test_secret_leak(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="+Authorization: Bearer sk-1234567890abcdefghij",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        # Either policy_check or explicit secret check may catch it first
        assert "secret" in result.reason.lower() or "policy" in result.reason.lower()
