"""Tests for evolver.gep.llm_review."""

from unittest.mock import patch

import pytest

from evolver.gep.llm_review import (
    LLMReviewResult,
    MIN_CONFIDENCE,
    _build_prompt,
    _parse_review_response,
    is_approved,
    review_diff,
)


class TestBuildPrompt:
    def test_contains_diff(self):
        prompt = _build_prompt("+line1", "summary")
        assert "+line1" in prompt
        assert "summary" in prompt

    def test_contains_constraints(self):
        prompt = _build_prompt("+line1", "summary")
        assert "secrets" in prompt.lower()


class TestParseResponse:
    def test_valid_json(self):
        text = '{"approved": true, "confidence": 0.9, "concerns": []}'
        result = _parse_review_response(text)
        assert result.approved
        assert result.confidence == 0.9

    def test_markdown_code_block(self):
        text = '```json\n{"approved": false, "confidence": 0.3, "concerns": ["x"]}\n```'
        result = _parse_review_response(text)
        assert not result.approved
        assert result.confidence == 0.3
        assert "x" in result.concerns

    def test_unparseable(self):
        result = _parse_review_response("not json")
        assert not result.approved
        assert result.confidence == 0.0


class TestIsApproved:
    def test_approved_high_confidence(self):
        result = LLMReviewResult(approved=True, confidence=0.8)
        assert is_approved(result)

    def test_approved_low_confidence(self):
        result = LLMReviewResult(approved=True, confidence=0.5)
        assert not is_approved(result)

    def test_not_approved(self):
        result = LLMReviewResult(approved=False, confidence=0.9)
        assert not is_approved(result)


class TestReviewDiff:
    def test_feature_flag_off(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_REVIEW", "0")
        result = review_diff("+hello")
        assert result.approved

    def test_secret_leak_blocks(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_REVIEW", "1")
        result = review_diff("+Bearer sk-1234567890abcdefghij")
        assert not result.approved
        assert "Secret leak" in result.concerns[0]

    def test_llm_failure(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_REVIEW", "1")
        with patch("evolver.gep.llm_review._call_llm", side_effect=RuntimeError("timeout")):
            result = review_diff("+hello")
        assert not result.approved
