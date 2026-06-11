"""Tests for auto_distill_conv and auto_distill_llm."""

import json
import tempfile
from pathlib import Path

import pytest

from evolver.gep.auto_distill_conv import DistillSummary, distill_and_append, distill_window
from evolver.gep.auto_distill_llm import LLMDistillResult, distill_and_append as llm_distill_and_append, distill_llm_response


class TestAutoDistillConv:
    def test_empty_events(self):
        result = distill_window(events=[], window_seconds=3600)
        assert result is None

    def test_distill_themes(self):
        events = [
            {"type": "signal", "timestamp": 1000000, "description": "add auth"},
            {"type": "signal", "timestamp": 1000001, "description": "add auth"},
            {"type": "hypothesis", "timestamp": 1000002, "hypothesis": "use jwt"},
        ]
        result = distill_window(events=events, window_seconds=10, now=1000010)
        assert result is not None
        assert "add auth" in result.themes
        assert "use jwt" in result.themes
        assert 0 < result.confidence <= 1.0

    def test_distill_decisions(self):
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "switched to asyncio"},
        ]
        result = distill_window(events=events, window_seconds=10, now=1000010)
        assert result is not None
        assert "switched to asyncio" in result.decisions

    def test_distill_failures(self):
        events = [
            {"type": "attempt", "timestamp": 1000000, "error": "timeout"},
            {"type": "attempt", "timestamp": 1000001, "outcome": "test failed"},
        ]
        result = distill_window(events=events, window_seconds=10, now=1000010)
        assert result is not None
        assert "timeout" in result.failures
        assert "test failed" in result.failures

    def test_distill_and_append(self, tmp_path):
        import time
        path = tmp_path / "events.jsonl"
        now = time.time()
        events = [
            {"type": "signal", "timestamp": now, "description": "refactor"},
        ]
        # Pre-populate file
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        result = distill_and_append(window_seconds=10, path=path)
        assert result is not None
        lines = path.read_text().strip().splitlines()
        last = json.loads(lines[-1])
        assert last["type"] == "distill"


class TestAutoDistillLLM:
    def test_extract_facts(self):
        text = "- The API should be RESTful.\n- Data is stored in JSONL."
        result = distill_llm_response(text)
        assert any("API" in f for f in result.facts)

    def test_extract_rules(self):
        text = "Rule: Never commit secrets.\nAlways validate input."
        result = distill_llm_response(text)
        assert any("secrets" in r for r in result.rules)

    def test_extract_patterns(self):
        text = 'Pattern: Use context managers.\n"""Docstring here."""'
        result = distill_llm_response(text)
        assert any("context managers" in p for p in result.patterns)

    def test_extract_decisions(self):
        text = "Decision: Switch to Pydantic.\nWe chose to use uv."
        result = distill_llm_response(text)
        assert any("Pydantic" in d for d in result.decisions)

    def test_confidence(self):
        text = "Fact: A.\nRule: B.\nPattern: C.\nDecision: D."
        result = distill_llm_response(text)
        assert result.confidence > 0

    def test_distill_and_append(self, tmp_path):
        path = tmp_path / "events.jsonl"
        result = llm_distill_and_append("Fact: testing.", source="test", path=path)
        assert any("testing" in f for f in result.facts)
        lines = path.read_text().strip().splitlines()
        last = json.loads(lines[-1])
        assert last["type"] == "llm_distill"
        assert last["source"] == "test"
