"""Tests for evolver.adapters.scripts.signal_detect.

Covers the contracts ported from evolver-signal-detect.js:
  - stratify_content: strips comments/code structure
  - detect_signals: keyword matching + multilingual fallback
  - build_signal_output: payload extraction + context formatting

Equivalent to test/signalDetect.test.js.
"""

from __future__ import annotations

from evolver.adapters.scripts import signal_detect

# ---------------------------------------------------------------------------
# stratify_content
# ---------------------------------------------------------------------------


class TestStratifyContent:
    def test_strips_comments(self) -> None:
        text = "// this has an error\nreal line with content"
        result = signal_detect.stratify_content(text)
        assert "// this has an error" not in result
        assert "real line with content" in result

    def test_strips_hash_comments(self) -> None:
        text = "# a comment\na real line"
        result = signal_detect.stratify_content(text)
        assert "# a comment" not in result

    def test_strips_braces(self) -> None:
        text = "{\nreal text\n}"
        result = signal_detect.stratify_content(text)
        assert "{" not in result
        assert "}" not in result


# ---------------------------------------------------------------------------
# detect_signals
# ---------------------------------------------------------------------------


class TestDetectSignals:
    def test_error_signal(self) -> None:
        result = signal_detect.detect_signals("Error: something went wrong")
        assert "log_error" in result

    def test_perf_signal(self) -> None:
        result = signal_detect.detect_signals("Request timeout after 30s")
        assert "perf_bottleneck" in result

    def test_capability_gap(self) -> None:
        result = signal_detect.detect_signals("This feature is not implemented yet")
        assert "capability_gap" in result

    def test_test_failure(self) -> None:
        result = signal_detect.detect_signals("assertion failed in test")
        assert "test_failure" in result

    def test_empty_input(self) -> None:
        assert signal_detect.detect_signals("") == []
        assert signal_detect.detect_signals(None) == []

    def test_no_false_positive_in_comment(self) -> None:
        # After stratification, comment lines (starting with #) are stripped,
        # so keywords in comments don't trigger signals.
        result = signal_detect.detect_signals("# timeout config here\nx = 1")
        assert "perf_bottleneck" not in result

    def test_multilingual_fallback(self) -> None:
        # CJK error characters trigger the multilingual fallback.
        result = signal_detect.detect_signals("\u53d1\u751f\u9519\u8bef")
        assert "log_error" in result

    def test_multiple_signals(self) -> None:
        result = signal_detect.detect_signals("Error: timeout while running tests")
        assert "log_error" in result
        assert "perf_bottleneck" in result

    def test_dedup(self) -> None:
        result = signal_detect.detect_signals("error: error: error")
        assert result.count("log_error") == 1


# ---------------------------------------------------------------------------
# build_signal_output
# ---------------------------------------------------------------------------


class TestBuildSignalOutput:
    def test_claude_code_payload(self) -> None:
        payload = {
            "tool_input": {
                "file_path": "/proj/main.py",
                "new_string": "error: connection failed",
            }
        }
        result = signal_detect.build_signal_output(payload)
        assert "additional_context" in result
        assert "log_error" in result["additional_context"]
        assert "/proj/main.py" in result["additional_context"]

    def test_raw_payload(self) -> None:
        payload = {"content": "the build failed in CI", "path": "/proj/x.py"}
        result = signal_detect.build_signal_output(payload)
        assert "additional_context" in result

    def test_no_signals_empty(self) -> None:
        payload = {"content": "hello world", "path": "/proj/x.py"}
        result = signal_detect.build_signal_output(payload)
        assert result == {}

    def test_both_context_keys(self) -> None:
        payload = {"content": "error: something failed", "path": "/p"}
        result = signal_detect.build_signal_output(payload)
        assert "additional_context" in result
        assert "additionalContext" in result
