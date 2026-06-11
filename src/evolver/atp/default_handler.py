"""Default ATP order handler for evolver loop mode.

Equivalent to ``evolver/src/atp/defaultHandler.js``.
Processes incoming ATP orders with a generic response.
Users can override by providing a custom onOrder callback via
``EVOLVER_ATP_SERVICES``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


def default_order_handler(order: dict[str, Any]) -> dict[str, Any]:
    """Return a generic processed result for an ATP order."""
    title = str(order.get("title", "")).lower()
    signals = str(order.get("signals", "")).lower()

    if "review" in title or "code_review" in signals or "bug" in signals:
        result = "Code review processed by evolver. Analysis complete."
    elif "translat" in title or "translation" in signals or "localization" in signals:
        result = "Translation processed by evolver. Output ready."
    elif "summar" in title or "summarization" in signals or "digest" in signals:
        result = "Summarization processed by evolver. Digest generated."
    else:
        result = "Task processed by evolver agent."

    return {
        "result": result,
        "output": result,
        "pass_rate": 1.0,
        "processed_at": datetime.now(UTC).isoformat(),
        "processor": "evolver-default",
    }


def resolve_atp_services(
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve ATP service definitions from env or defaults."""
    effective_env = env if env is not None else dict(os.environ)
    env_services = effective_env.get("EVOLVER_ATP_SERVICES", "")
    if env_services:
        try:
            parsed = json.loads(env_services)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except json.JSONDecodeError:
            # Log would go here in a real app
            pass

    agent_name = (
        effective_env.get("EVOLVER_AGENT_NAME", "")
        or effective_env.get("EVOLVER_MODEL_NAME", "")
        or "Evolver Agent"
    ).strip()

    return [
        {
            "title": f"{agent_name} - Code Evolution",
            "description": ("Automated code evolution, bug fixes, and code review powered by GEP."),
            "capabilities": ["code_evolution", "bug_fix", "code_review", "refactoring"],
            "useCases": ["Automated repair", "Code quality", "Evolution cycle"],
            "pricePerTask": 5,
            "maxConcurrent": 3,
        },
    ]


def get_atp_mode(env: dict[str, str] | None = None) -> str:
    """Return the ATP mode: 'on', 'off', or 'auto'."""
    effective_env = env if env is not None else dict(os.environ)
    raw = effective_env.get("EVOLVER_ATP", "auto").lower().strip()
    if raw in ("off", "false", "0"):
        return "off"
    if raw in ("on", "true", "1"):
        return "on"
    return "auto"
