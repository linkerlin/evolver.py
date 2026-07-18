"""Cross-implementation savings formula family (savings-core spec).

Equivalent to ``evolver/src/gep/savingsCore.js``.  Every consumer of the
savings-core spec (evomap-hub, evomap-private, Node evolver, this port) must
replay ``conformance/savings-core/golden-vectors.json`` bit-for-bit against
the vendored ``constants.json``.  Both files are vendored verbatim under
``evolver/assets/conformance/savings-core/`` and loaded here as the single
source of constants — no copy to drift.

JS ``Math.round`` rounds half away from zero; Python's ``round`` is banker's
rounding, so the helpers below reimplement JS semantics.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

#: JS Number.EPSILON, applied before rounding exactly like the reference impl.
_EPSILON = 2.220446049250313e-16


def _vendor_dir() -> Path:
    import evolver  # noqa: PLC0415  (mirror paths.get_bundled_gep_assets_dir)

    return Path(evolver.__file__).resolve().parent / "assets" / "conformance" / "savings-core"


def constants_path() -> Path:
    return _vendor_dir() / "constants.json"


def golden_vectors_path() -> Path:
    return _vendor_dir() / "golden-vectors.json"


CONSTANTS: dict[str, Any] = json.loads(constants_path().read_text(encoding="utf-8"))
SAVINGS_SPEC_VERSION: str = CONSTANTS["spec_version"]


def _js_round(value: float) -> int:
    """JS Math.round: half away from zero (positive domain: floor(x+0.5))."""
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def _round2(value: float) -> float:
    return _js_round((value + _EPSILON) * 100) / 100


def _round4(value: float) -> float:
    return _js_round((value + _EPSILON) * 10000) / 10000


def _to_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _clamp_tokens(value: Any) -> int:
    """Coerce to a non-negative rounded token count (JS: max(0, round(Number(x)||0)))."""
    return max(0, _js_round(_to_number(value)))


def measured_savings(raw_tokens: Any, optimized_tokens: Any) -> dict[str, Any]:
    """R1: real measured savings between a raw and an optimized run."""
    raw = _clamp_tokens(raw_tokens)
    optimized = _clamp_tokens(optimized_tokens)
    tokens_saved = max(0, raw - optimized)
    fraction = max(0.0, 1.0 - optimized / raw) if raw > 0 else 0.0
    return {"tokens_saved": tokens_saved, "savings_pct": _round2(fraction * 100)}


def rollout_fold_pct(n_avg_rollouts: Any) -> float:
    """R2: rollout fold percentage from the average rollout count."""
    n = _to_number(n_avg_rollouts)
    if n < 1:
        return 0
    return _round2((1.0 - 1.0 / n) * 100)


def entropy_total(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    """E1: entropy-avoidance rollup over typed events.

    Caller-supplied ``tokensEstSaved`` takes precedence over the constant
    coefficient; unknown event types without a measured value are ignored.
    """
    coefficients = CONSTANTS["entropy_event_tokens_est"]
    total_tokens_saved = 0
    total_events = 0
    for event in events or []:
        measured = event.get("tokensEstSaved")
        if measured is not None:
            per_event = _clamp_tokens(measured)
        else:
            coefficient = coefficients.get(event.get("type"))
            if coefficient is None:
                continue
            per_event = coefficient
        count = _clamp_tokens(event.get("count") if event.get("count") is not None else 1)
        total_tokens_saved += per_event * count
        total_events += count
    return {"total_tokens_saved": total_tokens_saved, "total_events": total_events}


def fetch_usage_estimate(by_type: dict[str, Any] | None) -> int:
    """E2: estimated tokens saved from fetched asset usage, by asset type."""
    coefficients = CONSTANTS["fetch_usage_tokens_est"]
    total = 0
    for asset_type, count in (by_type or {}).items():
        coefficient = coefficients.get(asset_type)
        total += (coefficient if coefficient is not None else 0) * _clamp_tokens(count)
    return total


def reuse_estimate(blast_radius_lines: Any, mode: Any = None) -> dict[str, Any]:
    """E3: estimated tokens a reuse avoided, anchored on blast-radius lines."""
    estimator = CONSTANTS["reuse_estimator"]
    n = _to_number(blast_radius_lines)
    has_lines = (
        isinstance(blast_radius_lines, (int, float))
        and not isinstance(blast_radius_lines, bool)
        and math.isfinite(n)
        and n > 0
    )
    basis = "estimated_blast_radius" if has_lines else "estimated_default"
    lines = n if has_lines else estimator["typical_changed_lines"]
    derived = min(
        estimator["derive_base_tokens"] + lines * estimator["tokens_per_changed_line"],
        estimator["derive_cap_tokens"],
    )
    if mode == "reference":
        derived *= estimator["reference_saving_fraction"]
    return {"tokens_saved": _js_round(derived), "basis": basis}


def hit_rate_pct(hits: Any, misses: Any) -> float:
    """H1: hub search hit rate percentage."""
    hit_count = _clamp_tokens(hits)
    miss_count = _clamp_tokens(misses)
    total = hit_count + miss_count
    if total <= 0:
        return 0
    return _round2(hit_count / total * 100)


def usd_saved(tokens: Any) -> float:
    """U1: blended USD value of saved tokens."""
    return _round2(_clamp_tokens(tokens) / 1_000_000 * CONSTANTS["usd_per_m_tokens_blended"])


def cache_saved_usd(provider: Any, cache_read_tokens: Any) -> float:
    """C1: USD saved by provider cache reads."""
    coefficient = CONSTANTS["cache_read_saved_usd_per_m_tokens"].get(provider)
    rate = coefficient if coefficient is not None else 0
    return _round4(_clamp_tokens(cache_read_tokens) / 1_000_000 * rate)


__all__ = [
    "CONSTANTS",
    "SAVINGS_SPEC_VERSION",
    "cache_saved_usd",
    "constants_path",
    "entropy_total",
    "fetch_usage_estimate",
    "golden_vectors_path",
    "hit_rate_pct",
    "measured_savings",
    "reuse_estimate",
    "rollout_fold_pct",
    "usd_saved",
]
