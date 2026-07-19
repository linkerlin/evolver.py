"""Asset call log observer — reuse attribution, cost index, call summaries for WebUI."""

from __future__ import annotations

from typing import Any

from evolver.gep.asset_call_log import (
    asset_cost_index,
    read_call_log,
    reuse_attribution_summary,
    summarize_call_log,
)


def call_log_summary(
    *, run_id: str | None = None, last: int | None = None, since: str | None = None
) -> dict[str, Any]:
    """Aggregated call log summary with optional filters."""
    opts: dict[str, Any] = {}
    if run_id:
        opts["run_id"] = run_id
    if last:
        opts["last"] = last
    if since:
        opts["since"] = since
    return summarize_call_log(opts)


def reuse_summary(*, run_id: str | None = None, last: int | None = None) -> dict[str, Any]:
    """Reuse attribution rollup per asset."""
    opts: dict[str, Any] = {}
    if run_id:
        opts["run_id"] = run_id
    if last:
        opts["last"] = last
    return reuse_attribution_summary(opts)


def cost_index() -> dict[str, int]:
    """Map asset_id → tokens spent to derive it."""
    return asset_cost_index()


def recent_calls(*, last: int = 100) -> list[dict[str, Any]]:
    """Return recent call log entries."""
    return read_call_log({"last": last})


def calls_by_run(run_id: str) -> list[dict[str, Any]]:
    """Return all call log entries for a specific run."""
    return read_call_log({"run_id": run_id})
