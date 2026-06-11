"""Tests for evolver.gep.analyzer."""

from __future__ import annotations

from evolver.gep.analyzer import CauseCategory, analyze


class TestAnalyze:
    def test_module_not_found(self):
        d = analyze("Traceback: ModuleNotFoundError: No module named 'numpy'")
        assert d.category == CauseCategory.ENVIRONMENT
        assert d.confidence >= 0.9
        assert "numpy" in d.cause

    def test_assertion(self):
        d = analyze("AssertionError: assert 1 == 2")
        assert d.category == CauseCategory.TEST
        assert d.confidence >= 0.85

    def test_syntax(self):
        d = analyze("SyntaxError: invalid syntax\n  print(")
        assert d.category == CauseCategory.CODE
        assert d.confidence >= 0.9

    def test_timeout(self):
        d = analyze("Connection timed out after 30 seconds")
        assert d.category == CauseCategory.INFRASTRUCTURE

    def test_connection(self):
        d = analyze("Connection refused to hub.example:443")
        assert d.category == CauseCategory.NETWORK

    def test_permission(self):
        d = analyze("Permission denied: /etc/shadow")
        assert d.category == CauseCategory.ENVIRONMENT

    def test_key_error(self):
        d = analyze("KeyError: 'missing_key'")
        assert d.category == CauseCategory.CODE
        assert "missing_key" in d.cause

    def test_type_error(self):
        d = analyze("TypeError: foo() takes 1 positional argument but 2 were given")
        assert d.category == CauseCategory.CODE

    def test_unknown(self):
        d = analyze("Something completely random happened.")
        assert d.category == CauseCategory.UNKNOWN
        assert d.confidence < 0.5

    def test_context_ignored(self):
        # context is accepted but not used by current matchers
        d = analyze("Timeout", context={"command": "pytest"})
        assert d.category == CauseCategory.INFRASTRUCTURE
