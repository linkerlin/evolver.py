"""Solve cost capture (经验即证据 §5.7) — 采集先行.

The receipt is written BEFORE the solve (it records what the solve saw), so
token usage and model config are only knowable AFTER. This module fills the
receipt's ``cost``/``model`` fields once they are observable.

Observation sources:
- tokens: relay-side ``proxy/trace/extractor.extract_usage`` (the relay sees
  the LLM traffic); the host's own accounting is a clue, not evidence.
- model: relay-observed model name; ``AGENT_MODEL`` is a clue (self-reported).

Unobservable → the fields stay ``null`` (``unmeasured``). A solve whose cost
was not observed says so explicitly — never guessed, never zero-filled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

COST_FORMAT: Final = "evolver.solve_cost.v0"


def record_cost(
    receipt_path: Path,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
) -> dict[str, Any]:
    """Fill the receipt's cost/model after a solve.

    Reads the existing receipt (preserving its provenance fields), sets the
    ``cost`` and ``model`` fields, writes back. A second call overwrites the
    cost — the latest observation wins.
    """
    path = Path(receipt_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError(f"receipt is not a JSON object: {path}")
    receipt["cost"] = {
        "format": COST_FORMAT,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
    }
    receipt["model"] = model
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


def read_cost(receipt_path: Path) -> dict[str, Any]:
    """Read one solve's cost. ``unmeasured`` when the fields are null."""
    path = Path(receipt_path)
    if not path.exists():
        return {"status": "unmeasured", "reason": "no_receipt"}
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        return {"status": "unmeasured", "reason": "malformed_receipt"}
    cost = receipt.get("cost")
    model = receipt.get("model")
    if cost is None and model is None:
        return {"status": "unmeasured"}
    return {
        "status": "measured",
        "cost": cost,
        "model": model,
    }


__all__ = ["COST_FORMAT", "read_cost", "record_cost"]
