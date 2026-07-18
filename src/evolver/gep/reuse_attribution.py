"""Reuse-attribution block builder + optional Hub outcome report (P4-a).

Equivalent to the reuse-attribution / outcome-report wiring in Node
``memoryGraph.recordOutcomeFromState`` + config flag parsers.

Money-adjacent safety:
- Client never emits ``source_node_id`` (anti-sybil: hub resolves payee).
- Attribution only when ``EVOLVER_REUSE_ATTRIBUTION=shadow`` and a real
  reuse/reference occurred in the *same* cycle as the outcome attempt.
- Hub POST only when ``EVOLVER_OUTCOME_REPORT=on`` and source_type is direct
  ``reused`` (not weaker ``reference``).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from evolver.config import outcome_report_mode, resolve_hub_url, reuse_attribution_mode

logger = logging.getLogger(__name__)

REUSE_ATTR_SCHEMA: str = "reuse_attr/1.0"
_REUSE_SOURCE_TYPES: frozenset[str] = frozenset({"reused", "reference"})


def _parse_iso_ts(raw: Any) -> float | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def build_reuse_attribution(
    last_run: dict[str, Any] | None,
    last_action: dict[str, Any] | None = None,
    *,
    mode: str | None = None,
) -> dict[str, Any] | None:
    """Build a ``reuse_attr/1.0`` block or return ``None``.

    Contract (Node ``reuseAttribution.test.js``):
    - mode must be ``shadow`` (``on``/garbage → off client-side)
    - ``source_type`` in {reused, reference}
    - ``last_run.created_at`` present and >= ``last_action.created_at`` (same cycle)
    - never includes client ``source_node_id`` / ``reused_source_node``
    """
    effective = mode if mode is not None else reuse_attribution_mode()
    if effective != "shadow":
        return None
    if not isinstance(last_run, dict):
        return None

    source_type = last_run.get("source_type")
    if source_type not in _REUSE_SOURCE_TYPES:
        return None

    run_created = _parse_iso_ts(last_run.get("created_at"))
    if run_created is None:
        # Cannot correlate cycle without created_at (legacy / uncorrelatable).
        return None

    if isinstance(last_action, dict):
        action_created = _parse_iso_ts(last_action.get("created_at") or last_action.get("ts"))
        if action_created is not None and run_created < action_created:
            # Stale last_run from a prior cycle (Bugbot #186).
            return None

    asset_id = last_run.get("reused_asset_id")
    if asset_id is not None and not isinstance(asset_id, str):
        asset_id = str(asset_id) if asset_id else None

    chain_id = last_run.get("reused_chain_id")
    if chain_id is not None and not isinstance(chain_id, str):
        chain_id = str(chain_id) if chain_id else None

    block: dict[str, Any] = {
        "schema": REUSE_ATTR_SCHEMA,
        "source_type": source_type,
        "reused_asset_id": asset_id,
        "reused_chain_id": chain_id,
    }
    # Explicitly refuse to copy payee claims from the client run-state.
    assert "source_node_id" not in block
    assert "reused_source_node" not in block
    return block


def build_outcome_report_payload(  # noqa: PLR0911
    *,
    last_run: dict[str, Any] | None,
    last_action: dict[str, Any] | None,
    signals: list[str],
    status: str,
    sender_id: str | None,
    attribution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Flat body for ``POST /a2a/memory/record`` when outcome report is on.

    Only direct ``reused`` claims ``used_asset_ids``; ``reference`` is weaker
    and must not POST. Requires non-empty ``sender_id``.
    """
    if outcome_report_mode() != "on":
        return None
    if not isinstance(last_run, dict):
        return None
    if last_run.get("source_type") != "reused":
        return None
    if not isinstance(attribution, dict):
        return None
    asset_id = attribution.get("reused_asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        return None
    if not isinstance(sender_id, str) or not sender_id.strip():
        return None

    # Prefer action signals when current cycle signals are empty (error cleared).
    action_signals: list[str] = []
    if isinstance(last_action, dict):
        raw = last_action.get("signals")
        if isinstance(raw, list):
            action_signals = [str(s) for s in raw if s]

    report_signals = list(signals) if signals else action_signals
    if not report_signals:
        report_signals = ["outcome"]

    return {
        "sender_id": sender_id.strip(),
        "signals": report_signals,
        "status": status,
        "used_asset_ids": [asset_id],
    }


def post_outcome_report(payload: dict[str, Any]) -> bool:
    """Best-effort POST to Hub ``/a2a/memory/record``. Never raises."""
    hub = resolve_hub_url()
    if not hub:
        return False
    url = hub.rstrip("/") + "/a2a/memory/record"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = (
        os.environ.get("A2A_NODE_SECRET") or os.environ.get("EVOMAP_NODE_SECRET") or ""
    ).strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        return bool(resp.is_success)
    except Exception as exc:
        logger.debug("[reuse_attribution] outcome report failed: %s", exc)
        return False


def utc_now_iso() -> str:
    """UTC ISO-8601 timestamp with Z suffix (for last_run.created_at)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "REUSE_ATTR_SCHEMA",
    "build_outcome_report_payload",
    "build_reuse_attribution",
    "post_outcome_report",
    "utc_now_iso",
]
