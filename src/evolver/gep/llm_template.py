"""Externalized, reproducible LLM call templates.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``run_self_harness_loop.py`` ``run_external_template``). No Node.js
equivalent; evolver.py self-research addition (Sprint D).

The orchestrator never constructs an LLM client itself: the diagnosis (B1)
and proposer (C2) LLM invocations are shell command templates with
placeholders (``{prompt}`` / ``{diagnosis}`` / ``{response}``), executed via
:func:`run_external_template`. Every call records its input and output to
disk (``<LLM_CALL_DIR>/<ts>_<kind>_in.json`` / ``_out.txt``) so the whole
loop is auditable and replayable.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Final

from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_gep_assets_dir

PLACEHOLDERS = ("{prompt}", "{diagnosis}", "{response}")

#: Shell command-substitution constructs (round-29, Mimosa triage): a value
#: carrying one of these and substituted RAW into a shell template becomes
#: executable code. Free-text payloads must go through the ``{<name>_file}``
#: placeholder instead — the engine writes the value to disk and passes a path.
_COMMAND_SUBSTITUTION_MARKERS: Final[tuple[str, ...]] = ("`", "$(")


def _resolve_call_dir() -> Path:
    """Resolve the LLM call dir; ``<GEP_ASSETS_DIR>`` expands to the real one."""
    env = os.environ.get("EVOLVER_LLM_CALL_DIR", "")
    if env:
        return Path(env).expanduser()
    return get_gep_assets_dir() / "llm_calls"


def render_template(template: str, placeholders: dict[str, str]) -> str:
    """Substitute known placeholders into *template*.

    Unknown ``{...}`` sequences are left untouched (so templates can carry
    shell syntax safely). ``{prompt}`` is written to a temp file and passed by
    path when a ``{prompt_file}`` placeholder is present (avoids ARG_MAX for
    large prompts).
    """
    result = template
    for key, value in placeholders.items():
        result = result.replace("{" + key + "}", value)
    return result


def _raw_injection_risk_key(template: str, placeholders: dict[str, str]) -> str | None:
    """First placeholder substituted RAW whose value could execute in the shell.

    Only keys whose ``{key}`` spelling appears in the template are checked:
    a value passed via the ``{<name>_file}`` mechanism is written to disk by
    the caller and enters the command as an engine-generated path, so its
    text never reaches the shell parser.
    """
    for key, value in placeholders.items():
        if "{" + key + "}" not in template:
            continue
        if any(marker in value for marker in _COMMAND_SUBSTITUTION_MARKERS):
            return key
    return None


def run_external_template(
    template: str,
    placeholders: dict[str, str],
    *,
    kind: str = "llm",
    timeout_s: float = 120.0,
    record: bool = True,
) -> str:
    """Run *template* with *placeholders* substituted; return stdout.

    When ``record`` is enabled (default), the rendered command, input
    placeholders, and stdout are persisted under the LLM call dir for
    audit/replay. Returns ``""`` on timeout/OSError (caller decides).

    Fail-safe (round-29, Mimosa triage): a placeholder value substituted RAW
    into the shell command that carries a command-substitution construct
    (backtick / ``$(``) is refused — nothing executes, a ``_refused.txt``
    marker records why, and ``""`` is returned. Free-text payloads belong in
    the ``{<name>_file}`` placeholder; the refusal message says so.
    """
    command = render_template(template, placeholders)
    if record:
        call_dir = _resolve_call_dir()
        call_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        stamp = f"{ts}_{kind}"
        (call_dir / f"{stamp}_in.json").write_text(
            json.dumps(
                {"template": template, "placeholders": placeholders},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    risky = _raw_injection_risk_key(template, placeholders)
    if risky is not None:
        if record:
            (call_dir / f"{stamp}_refused.txt").write_text(
                f"refused: raw placeholder '{risky}' carries a shell "
                "command-substitution construct; pass free-text payloads via "
                "the {<name>_file} placeholder\n",
                encoding="utf-8",
            )
        return ""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        stdout = proc.stdout or ""
        if record:
            (call_dir / f"{stamp}_out.txt").write_text(stdout, encoding="utf-8")
        return stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def build_llm_call(
    template: str | None,
    *,
    kind: str,
    placeholders: dict[str, str],
) -> str | None:
    """Build a concrete LLM call: run template or fall back to no-op.

    Returns the model output, or ``None`` when no template is configured
    (``EVOLVER_LLM_TEMPLATE`` off / empty template). The call is recorded for
    replay when enabled.
    """
    if not is_enabled("enable_llm_template"):
        return None
    if not template or not template.strip():
        return None
    return run_external_template(template, placeholders, kind=kind)


__all__ = [
    "PLACEHOLDERS",
    "build_llm_call",
    "render_template",
    "run_external_template",
]
