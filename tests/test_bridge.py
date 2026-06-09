"""Tests for evolver.gep.bridge — equivalent to evolver/test/bridge.test.js."""

from __future__ import annotations

import json

from evolver.gep import bridge


def test_render_sessions_spawn_call_roundtrip() -> None:
    line = bridge.render_sessions_spawn_call(
        {"task": "do the thing", "agentId": "main", "label": "gep_x", "cleanup": "delete"}
    )
    obj = bridge.parse_first_spawn_call(line)
    assert obj["task"] == "do the thing"
    assert obj["agentId"] == "main"
    assert obj["label"] == "gep_x"


def test_parse_first_spawn_call_takes_outer_call() -> None:
    inner_example = bridge.render_sessions_spawn_call(
        {
            "task": "exec: node skills/evolver/index.js evolve",
            "agentId": "main",
            "cleanup": "delete",
            "label": "gep_loop_next",
        }
    )
    real_task = f"Apply the patch.\nLoop chaining: after solidify, print:\n{inner_example}\n"
    real_line = bridge.render_sessions_spawn_call(
        {"task": real_task, "agentId": "main", "label": "gep_bridge_42"}
    )
    stdout = f"Starting evolver...\n{real_line}\nDone."
    obj = bridge.parse_first_spawn_call(stdout)
    assert obj["label"] == "gep_bridge_42"
    assert "Apply the patch" in obj["task"]


def test_parse_first_spawn_call_nested_braces() -> None:
    payload = {"a": {"b": [1, 2, {"c": 3}]}, "d": "}"}
    line = bridge.render_sessions_spawn_call({"task": json.dumps(payload), "agentId": "main"})
    obj = bridge.parse_first_spawn_call(line)
    task_obj = json.loads(obj["task"])
    assert task_obj["a"]["b"] == [1, 2, {"c": 3}]
    assert task_obj["d"] == "}"


def test_parse_first_spawn_call_literal_braces() -> None:
    line = bridge.render_sessions_spawn_call(
        {"task": "text with a literal } brace and a { brace inside", "agentId": "main"}
    )
    obj = bridge.parse_first_spawn_call(line)
    assert obj["task"] == "text with a literal } brace and a { brace inside"


def test_extract_first_spawn_payload_no_marker() -> None:
    assert bridge.extract_first_spawn_payload("no spawn here") is None
    assert bridge.extract_first_spawn_payload("") is None
    assert bridge.extract_first_spawn_payload(None) is None


def test_extract_first_spawn_payload_unbalanced() -> None:
    assert bridge.extract_first_spawn_payload('sessions_spawn({"task":"unterminated') is None
