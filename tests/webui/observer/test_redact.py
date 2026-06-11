"""Tests for evolver.webui.observer.redact."""

from __future__ import annotations

from evolver.webui.observer.redact import redact_text


class TestRedactText:
    def test_bearer_token(self):
        text = "Authorization: Bearer abc123def456ghi789jkl"
        assert "<REDACTED>" in redact_text(text)
        assert "abc123" not in redact_text(text)

    def test_api_key(self):
        text = "api_key=super_secret_key_12345"
        result = redact_text(text)
        assert "<REDACTED>" in result
        assert "super_secret" not in result

    def test_sk_prefix(self):
        text = "sk-abcdefghijklmnopqrstuvwxyz12345"
        result = redact_text(text)
        assert "<REDACTED>" in result
        assert "sk-abc" not in result

    def test_password(self):
        text = "password=myP@ssw0rd"
        result = redact_text(text)
        assert "<REDACTED>" in result
        assert "myP@ssw0rd" not in result

    def test_no_secrets(self):
        text = "Hello world"
        assert redact_text(text) == "Hello world"

    def test_multiple_secrets(self):
        text = "Bearer abc123def456ghi789jkl and password=secret123"
        result = redact_text(text)
        assert result.count("<REDACTED>") == 2
