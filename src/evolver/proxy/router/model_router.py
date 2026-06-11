"""Model router: select optimal upstream and model based on request parameters.

Equivalent to evolver/src/proxy/router/modelRouter.js.
"""

from __future__ import annotations

import os
from typing import Any

TIER_ORDER = ["cheap", "mid", "expensive"]

DEFAULT_MODEL_FALLBACKS: dict[str, str] = {
    "claude-3-7-sonnet": "claude-3-5-sonnet",
    "claude-3-5-sonnet": "claude-3-haiku",
    "claude-3-opus": "claude-3-5-sonnet",
}


def get_upstream_preference() -> str:
    """Return the preferred upstream: 'anthropic' or 'bedrock'."""
    env = os.environ.get("EVOMAP_UPSTREAM", "").lower().strip()
    if env in ("anthropic", "bedrock"):
        return env
    return "anthropic"


def resolve_model(
    *,
    requested_model: str | None = None,
    tier_hint: str | None = None,
    feature_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the final model and upstream to use.

    Returns a dict with:
    - upstream: "anthropic" | "bedrock"
    - model: canonical model name
    - tier: "cheap" | "mid" | "expensive"
    - fallback_chain: list of fallback model names
    """
    feature_flags = feature_flags or {}

    upstream = get_upstream_preference()
    if feature_flags.get("force_upstream"):
        upstream = feature_flags["force_upstream"]

    # Tier resolution
    tier = tier_hint or "mid"
    if tier not in TIER_ORDER:
        tier = "mid"

    # Model resolution
    model = requested_model or "claude-3-5-sonnet"

    # Build fallback chain
    fallback_chain: list[str] = []
    current = model
    for _ in range(3):
        if current in DEFAULT_MODEL_FALLBACKS:
            current = DEFAULT_MODEL_FALLBACKS[current]
            fallback_chain.append(current)
        else:
            break

    # Downgrade protection: high-tier users should not accidentally downgrade to cheap
    user_tier = feature_flags.get("user_tier", "mid")
    if user_tier in ("expensive", "premium") and tier == "cheap":
        tier = "mid"

    return {
        "upstream": upstream,
        "model": model,
        "tier": tier,
        "fallback_chain": fallback_chain,
    }


def select_upstream_for_model(model: str) -> str:
    """Select upstream based on model name."""
    if "bedrock" in model.lower() or model.startswith("anthropic."):
        return "bedrock"
    return get_upstream_preference()


__all__ = [
    "DEFAULT_MODEL_FALLBACKS",
    "TIER_ORDER",
    "get_upstream_preference",
    "resolve_model",
    "select_upstream_for_model",
]
