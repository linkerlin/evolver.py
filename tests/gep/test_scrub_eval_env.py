"""Grading children do not inherit API keys or engine privilege switches."""

from __future__ import annotations

from evolver.gep.validation_env import scrub_eval_subprocess_env


def test_scrub_drops_keys_and_keeps_path() -> None:
    source = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-secret",
        "DEEPSEEK_API_KEY": "dk",
        "EVOLVER_HITL_MODE": "off",
        "EVOLVER_ACCEPTANCE_SHADOW": "1",
        "HOME": "/home/dev",
    }
    scrubbed = scrub_eval_subprocess_env(source)
    assert scrubbed["PATH"] == "/usr/bin"
    assert scrubbed["HOME"] == "/home/dev"
    assert "OPENAI_API_KEY" not in scrubbed
    assert "DEEPSEEK_API_KEY" not in scrubbed
    assert "EVOLVER_HITL_MODE" not in scrubbed
    assert "EVOLVER_ACCEPTANCE_SHADOW" not in scrubbed
    assert "OPENAI_API_KEY" in source
