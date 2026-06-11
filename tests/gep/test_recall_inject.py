"""Tests for evolver.gep.recall_inject."""

import pytest

from evolver.gep.recall_inject import (
    RecallMatch,
    _jaccard,
    _signal_fingerprint,
    format_recall_prompt,
    inject_recall,
    search_recalls,
)


class TestJaccard:
    def test_identical(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial(self):
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3, rel=0.01)

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0


class TestSignalFingerprint:
    def test_extracts_keywords(self):
        signals = ["add auth module", "fix login bug"]
        fp = _signal_fingerprint(signals)
        assert "auth" in fp
        assert "module" in fp
        assert "login" in fp
        assert "bug" in fp


class TestSearchRecalls:
    def test_empty_events(self):
        matches = search_recalls(["refactor"], events=[], top_k=3)
        assert matches == []

    def test_finds_memory_graph_outcome(self):
        events = [
            {
                "type": "MemoryGraphEvent",
                "kind": "outcome",
                "id": "e-mg",
                "ts": "2026-06-01T00:00:00.000Z",
                "signal": {"signals": ["refactor", "auth"]},
                "gene": {"id": "g1", "category": "repair"},
                "outcome": {"status": "success"},
            }
        ]
        matches = search_recalls(["refactor", "auth"], events=events, top_k=3)
        assert len(matches) == 1
        assert matches[0].event_id == "e-mg"

    def test_finds_successful(self):
        events = [
            {
                "type": "attempt",
                "event_id": "e1",
                "timestamp": 1000000,
                "outcome": "success",
                "signals_snapshot": ["add auth", "refactor login"],
                "mutation_summary": "added oauth",
            },
            {
                "type": "attempt",
                "event_id": "e2",
                "timestamp": 1000001,
                "outcome": "failure",
                "signals_snapshot": ["add auth", "refactor login"],
                "mutation_summary": "broke tests",
            },
        ]
        matches = search_recalls(["auth", "login"], events=events, top_k=3, min_similarity=0.1)
        assert len(matches) == 1
        assert matches[0].event_id == "e1"
        assert matches[0].similarity > 0

    def test_respects_min_similarity(self):
        events = [
            {
                "type": "attempt",
                "event_id": "e1",
                "timestamp": 1000000,
                "outcome": "success",
                "signals_snapshot": ["totally different topic"],
                "mutation_summary": "irrelevant",
            },
        ]
        matches = search_recalls(["auth", "login"], events=events, top_k=3, min_similarity=0.5)
        assert matches == []

    def test_top_k_limit(self):
        events = [
            {
                "type": "attempt",
                "event_id": f"e{i}",
                "timestamp": 1000000 + i,
                "outcome": "success",
                "signals_snapshot": ["add auth"],
                "mutation_summary": f"mutation {i}",
            }
            for i in range(10)
        ]
        matches = search_recalls(["auth"], events=events, top_k=3)
        assert len(matches) == 3


class TestFormatRecallPrompt:
    def test_empty(self):
        assert format_recall_prompt([]) == ""

    def test_formats_matches(self):
        matches = [
            RecallMatch(
                event_id="e1",
                similarity=0.85,
                signals=["auth", "login"],
                mutation_summary="added oauth",
                outcome="success",
            ),
        ]
        prompt = format_recall_prompt(matches)
        assert "Recall Hints" in prompt
        assert "added oauth" in prompt
        assert "85%" in prompt


class TestInjectRecall:
    def test_inject(self):
        events = [
            {
                "type": "attempt",
                "event_id": "e1",
                "timestamp": 1000000,
                "outcome": "success",
                "signals_snapshot": ["add auth"],
                "mutation_summary": "added oauth",
            },
        ]
        prompt = inject_recall(["auth"], events=events, top_k=3)
        assert "added oauth" in prompt
