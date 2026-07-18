"""Gemini gateway tool-call reconstruction (Sprint 15.3 / FIX-2)."""

from __future__ import annotations

import json

from evolver.gep.trajectory import build_trajectory_from_rows


def test_non_streaming_function_call() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_gemini",
        [
            {
                "prism_compatible": True,
                "requestId": "req_gem",
                "createdAtIso": "2026-06-24T00:00:00.000Z",
                "sessionId": "sess_gemini",
                "path": "/v1beta/models/gemini-3-pro:generateContent",
                "upstream": "gemini",
                "model": "gemini-3-pro",
                "status": 200,
                "requestBody": json.dumps(
                    {
                        "contents": [
                            {"role": "user", "parts": [{"text": "List files in the repo root"}]}
                        ],
                        "tools": [{"functionDeclarations": [{"name": "list_dir"}]}],
                    }
                ),
                "responseBody": json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "role": "model",
                                    "parts": [
                                        {"text": "Let me look."},
                                        {
                                            "functionCall": {
                                                "name": "list_dir",
                                                "args": {"path": "."},
                                            }
                                        },
                                    ],
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 10,
                            "candidatesTokenCount": 5,
                        },
                    }
                ),
            }
        ],
    )
    assert trajectory is not None
    assert trajectory.stats.has_tool_calls is True
    calls = [
        c for c in trajectory.turns[0].tool_calls if not c.declared and c.name != "tool_result"
    ]
    list_dir = next((c for c in calls if c.name == "list_dir"), None)
    assert list_dir is not None
    assert list_dir.input == {"path": "."}


def test_streaming_function_call_and_response() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_gemini_stream",
        [
            {
                "prism_compatible": True,
                "requestId": "req_gem_stream",
                "createdAtIso": "2026-06-24T00:01:00.000Z",
                "sessionId": "sess_gemini_stream",
                "path": "/v1beta/models/gemini-3-pro:streamGenerateContent",
                "upstream": "gemini",
                "model": "gemini-3-pro",
                "status": 200,
                "isStream": True,
                "requestBody": json.dumps(
                    {
                        "contents": [
                            {"role": "user", "parts": [{"text": "run the tests"}]},
                            {
                                "role": "function",
                                "parts": [
                                    {
                                        "functionResponse": {
                                            "name": "run_tests",
                                            "response": {"ok": True},
                                        }
                                    }
                                ],
                            },
                        ]
                    }
                ),
                "responseBody": json.dumps(
                    {
                        "events": [
                            {
                                "candidates": [
                                    {"content": {"role": "model", "parts": [{"text": "ok"}]}}
                                ]
                            },
                            {
                                "candidates": [
                                    {
                                        "content": {
                                            "role": "model",
                                            "parts": [
                                                {
                                                    "functionCall": {
                                                        "name": "run_tests",
                                                        "args": {"suite": "unit"},
                                                    }
                                                }
                                            ],
                                        }
                                    }
                                ],
                                "usageMetadata": {
                                    "promptTokenCount": 3,
                                    "candidatesTokenCount": 2,
                                },
                            },
                        ]
                    }
                ),
            }
        ],
    )
    assert trajectory is not None
    assert trajectory.stats.has_tool_calls is True
    names = [c.name for c in trajectory.turns[0].tool_calls]
    assert "run_tests" in names
    assert "tool_result" in names
