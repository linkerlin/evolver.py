"""Tests for evolver.gep.bridge — sessions_spawn parsing + bridge-enabled logic.

Equivalent to test/bridge.test.js.
"""

from __future__ import annotations

import json

import pytest

from evolver.gep.bridge import (
    determine_bridge_enabled,
    extract_first_spawn_payload,
    parse_first_spawn_call,
    render_sessions_spawn_call,
)

# ---------------------------------------------------------------------------
# determine_bridge_enabled
# ---------------------------------------------------------------------------


class TestDetermineBridgeEnabled:
    def test_unset_no_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOLVE_BRIDGE", raising=False)
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        assert determine_bridge_enabled() is False

    def test_unset_with_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOLVE_BRIDGE", raising=False)
        monkeypatch.setenv("OPENCLAW_WORKSPACE", "/some/workspace")
        assert determine_bridge_enabled() is True

    def test_explicit_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "true")
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        assert determine_bridge_enabled() is True

    def test_explicit_false_overrides_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "false")
        monkeypatch.setenv("OPENCLAW_WORKSPACE", "/ws")
        assert determine_bridge_enabled() is False

    def test_case_insensitive_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "True")
        assert determine_bridge_enabled() is True

    def test_case_insensitive_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "False")
        assert determine_bridge_enabled() is False

    def test_truthy_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "1")
        assert determine_bridge_enabled() is True

    def test_empty_string_no_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "")
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        assert determine_bridge_enabled() is False

    def test_empty_string_with_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVE_BRIDGE", "")
        monkeypatch.setenv("OPENCLAW_WORKSPACE", "/ws")
        assert determine_bridge_enabled() is True


# ---------------------------------------------------------------------------
# sessions_spawn parsing
# ---------------------------------------------------------------------------


class TestSpawnCallParsing:
    def test_round_trip(self) -> None:
        line = render_sessions_spawn_call(
            {"task": "do the thing", "agentId": "main", "label": "gep_x", "cleanup": "delete"}
        )
        obj = parse_first_spawn_call(line)
        assert obj is not None
        assert obj["task"] == "do the thing"
        assert obj["agentId"] == "main"
        assert obj["label"] == "gep_x"
        assert obj["cleanup"] == "delete"

    def test_takes_first_not_last(self) -> None:
        inner_example = (
            'sessions_spawn({"task":"exec: node skills/evolver/index.js evolve",'
            '"agentId":"main","cleanup":"delete","label":"gep_loop_next"})'
        )
        real_task = (
            "Apply the patch following this prompt.\n"
            f"Loop chaining: after solidify, print:\n{inner_example}\n"
        )
        line = render_sessions_spawn_call(
            {"task": real_task, "agentId": "main", "label": "gep_bridge_42"}
        )
        stdout = f"Starting evolver...\nsome log line\n{line}\nEvolver finished."
        obj = parse_first_spawn_call(stdout)
        assert obj is not None
        assert obj["label"] == "gep_bridge_42"

    def test_nested_braces(self) -> None:
        nested = json.dumps({"a": {"b": [1, 2, {"c": 3}]}, "d": "}"})
        line = render_sessions_spawn_call({"task": nested, "agentId": "main"})
        obj = parse_first_spawn_call(line)
        assert obj is not None
        task_obj = json.loads(obj["task"])
        assert task_obj["a"]["b"] == [1, 2, {"c": 3}]
        assert task_obj["d"] == "}"

    def test_brace_in_string(self) -> None:
        line = render_sessions_spawn_call(
            {"task": "text with a literal } brace and a { brace inside", "agentId": "main"}
        )
        obj = parse_first_spawn_call(line)
        assert obj is not None
        assert obj["task"] == "text with a literal } brace and a { brace inside"

    def test_no_marker(self) -> None:
        assert extract_first_spawn_payload("just regular output, no spawn here") is None
        assert parse_first_spawn_call("nope") is None

    def test_empty_input(self) -> None:
        assert extract_first_spawn_payload("") is None
        assert extract_first_spawn_payload(None) is None

    def test_unbalanced_braces(self) -> None:
        assert extract_first_spawn_payload('sessions_spawn({"task":"unterminated') is None

    def test_malformed(self) -> None:
        assert extract_first_spawn_payload('sessions_spawn(garbage{"task":"x"})') is None

    def test_extract_returns_raw_string(self) -> None:
        line = render_sessions_spawn_call({"task": "T", "agentId": "a1"})
        raw = extract_first_spawn_payload(line)
        assert raw is not None
        assert isinstance(raw, str)
        parsed = parse_first_spawn_call(line)
        assert parsed == json.loads(raw)
