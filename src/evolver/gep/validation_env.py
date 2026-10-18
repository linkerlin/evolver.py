"""Shared subprocess environment for engine-spawned validation processes.

Extracted from :mod:`evolver.gep.solidify` (round-14): the acceptance gate
spawns its own pytest subprocesses (T0 discovery / repeats) and needs the
same PATH normalization as the validation cascade — GUI-spawned MCP hosts
propagate the launchd minimal PATH, bare ``pytest`` lookups fail there, and
``gate_or_none`` degrades the exception to ``None`` (gate silently disabled,
soak sample stops growing). One helper, two consumers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def validation_env() -> dict[str, str]:
    """Subprocess env for validation/acceptance commands.

    Never drops entries; prepends the well-known toolchain dirs (existing
    ones only) so the repo's own toolchain resolves regardless of how the
    engine process was spawned.

    Round-35 (DEBUG #41) exception: when the soak interlock auto-routed this
    process's runtime (``EVOLVER_SOAK_ROUTED`` sentinel), the routed
    ``EVOLUTION_DIR`` / ``GEP_ASSETS_DIR`` are ENGINE routing, not operator
    intent — the validated tree's own tests must resolve paths exactly as
    they would outside the engine. Explicitly-set values (no sentinel) are
    forwarded untouched.
    """
    env = dict(os.environ)
    if env.get("EVOLVER_SOAK_ROUTED"):
        env.pop("EVOLUTION_DIR", None)
        env.pop("GEP_ASSETS_DIR", None)
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    known = [
        str(Path(sys.executable).parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
    ]
    for directory in reversed(known):
        if directory not in parts and Path(directory).is_dir():
            parts.insert(0, directory)
    env["PATH"] = os.pathsep.join(parts)
    return env


#: Credentials and engine control knobs that must not enter a grading child.
_EVAL_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "ARC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "HF_TOKEN",
        "HUGGINGFACE_API_KEY",
        "EVOLVER_HITL_MODE",
        "EVOLVER_ACCEPTANCE_SHADOW",
        "EVOLVER_SWARM_AUTO_HIJACK",
        "EVOLVER_SWARM_GATE_HANDOFF",
    }
)


def _eval_secret_key(name: str) -> bool:
    upper = name.upper()
    if upper in _EVAL_SECRET_KEYS:
        return True
    return upper.endswith("_API_KEY") or upper.endswith("_API_TOKEN")


def scrub_eval_subprocess_env(env: dict[str, str]) -> dict[str, str]:
    """Copy *env* without API keys or engine privilege switches.

    Used by bench graders that execute task code. The engine's own validation
    cascade keeps :func:`validation_env` (PATH repair, no key dropping) so a
    repo's pytest still sees the operator environment it was launched with.
    """
    return {key: value for key, value in env.items() if not _eval_secret_key(key)}


__all__ = ["scrub_eval_subprocess_env", "validation_env"]
