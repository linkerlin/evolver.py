"""Tests for evolver.gep.sanitize."""

from __future__ import annotations

from evolver.gep.sanitize import (
    detect_env_value_leaks,
    full_leak_check,
    redact_string,
    sanitize_payload,
    scan_for_leaks,
)


class TestRedactString:
    def test_bearer(self):
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234"
        out = redact_string(text)
        assert "<REDACTED:BEARER>" in out

    def test_api_key(self):
        text = 'api_key = "supersecret1234567890"'
        out = redact_string(text)
        assert "<REDACTED:API_KEY>" in out

    def test_password(self):
        text = "password = hunter2secret"
        out = redact_string(text)
        assert "<REDACTED:PASSWORD>" in out

    def test_no_match(self):
        text = "hello world"
        assert redact_string(text) == text

    def test_non_string(self):
        assert redact_string(123) == 123


class TestScanForLeaks:
    def test_found(self):
        leaks = scan_for_leaks("Bearer abcdefghijklmnopqrstuvwxyz1234")
        assert len(leaks) == 1
        assert leaks[0]["type"] == "bearer"

    def test_none(self):
        assert scan_for_leaks("clean text") == []

    def test_bytes_input(self):
        leaks = scan_for_leaks(b"password = secret12345678")
        assert len(leaks) == 1


class TestDetectEnvValueLeaks:
    def test_no_leak(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR_XYZ", "unlikely_value_12345")
        payload = {"msg": "hello"}
        assert detect_env_value_leaks(payload) == []

    def test_leak(self, monkeypatch):
        monkeypatch.setenv("SECRET_TOKEN", "leaked_value_12345")
        payload = {"msg": "leaked_value_12345"}
        leaks = detect_env_value_leaks(payload)
        assert len(leaks) == 1
        assert leaks[0]["key"] == "SECRET_TOKEN"


class TestFullLeakCheck:
    def test_safe(self):
        result = full_leak_check({"msg": "hello"})
        assert result["safe"] is True

    def test_unsafe(self):
        result = full_leak_check({"token": "Bearer abcdefghijklmnopqrstuvwxyz1234"})
        assert result["safe"] is False
        assert len(result["pattern_leaks"]) > 0


class TestSanitizePayload:
    def test_dict(self):
        out = sanitize_payload({"key": "Bearer abcdefghijklmnopqrstuvwxyz1234"})
        assert "<REDACTED:BEARER>" in out

    def test_str(self):
        out = sanitize_payload("password = secret12345678")
        assert "<REDACTED:PASSWORD>" in out
