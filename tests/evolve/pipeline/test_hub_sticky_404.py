"""Tests for hub-phase sticky 404 short-circuit (round-45; round-48 API-based)."""

from __future__ import annotations

import time as _time
from typing import Any

import pytest

from evolver.evolve.pipeline import hub as hub_mod
from evolver.evolve.pipeline.hub import HUB_404_STICKY_THRESHOLD, hub_phase
from evolver.gep.hub_health import load_state, save_state


def _ctx() -> dict[str, Any]:
    return {"signals": ["log_error"]}


async def _run_with_fetch(monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> dict[str, Any]:
    calls = {"n": 0}

    async def fake_fetch(limit: int = 5, signals: list[str] | None = None) -> dict[str, Any]:
        idx = min(calls["n"], len(results) - 1)
        calls["n"] += 1
        item = results[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(hub_mod, "fetch_tasks", fake_fetch)
    ctx = _ctx()
    ctx["_calls"] = calls  # type: ignore[typeddict-unknown-key]
    out = await hub_phase(ctx)
    out["_calls"] = calls  # type: ignore[typeddict-unknown-key]
    return out


def _err_404() -> dict[str, Any]:
    return {"ok": False, "error": "Client error '404 Not Found' for url", "tasks": []}


def _err_network() -> dict[str, Any]:
    return {"ok": False, "error": "Connection reset by peer", "tasks": []}


def _ok() -> dict[str, Any]:
    return {"ok": True, "tasks": [], "hub_response": {}}


class TestSticky404:
    async def test_three_404s_then_sticky_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Burn the threshold with real fetches.
        for _ in range(HUB_404_STICKY_THRESHOLD):
            out = await _run_with_fetch(monkeypatch, [_err_404()])
            assert out["hub_hit"]["reason"] == "offline"
        # Next cycle: fetch is short-circuited entirely.
        out = await _run_with_fetch(monkeypatch, [_err_404()])
        assert out["hub_hit"]["reason"] == "hub_endpoint_missing"
        assert out["hub_hit"]["sticky"] is True
        assert out["_calls"]["n"] == 0, "sticky skip must not burn a fetch"
        assert "skip_hub_calls" not in out, (
            "sticky skip must keep the failed-fetch ctx shape — "
            "setting skip_hub_calls would idle the dispatch phase"
        )
        assert out["active_task"] is None

    async def test_ttl_expiry_reprobes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_state(
            {
                "consecutive_404": HUB_404_STICKY_THRESHOLD,
                "last_probe_ts": 0.0,  # ancient → TTL expired
                "skipped_cycles": 99,
            }
        )
        out = await _run_with_fetch(monkeypatch, [_ok()])
        assert out["_calls"]["n"] == 1, "expired TTL must re-probe"
        assert out["hub_hit"]["reason"] == "no_tasks"

    async def test_success_resets_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_state({"consecutive_404": 2, "last_probe_ts": 1.0e12, "skipped_cycles": 0})
        await _run_with_fetch(monkeypatch, [_ok()])
        assert load_state()["consecutive_404"] == 0

    async def test_failed_reprobe_halves_next_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Round-65: each failed sticky-state re-probe halves the next wait
        (floored at 1h) — a persistently dead endpoint converges to frequent
        cheap probes instead of a fresh 24h after every failed attempt."""
        from evolver.gep.hub_health import (
            HUB_404_REPROBE_S,
            endpoint_sticky,
        )

        # Sticky with a fresh re-probe failure: wait must be halved (24h/2),
        # still sticky because elapsed < halved wait.
        save_state(
            {
                "consecutive_404": HUB_404_STICKY_THRESHOLD + 2,  # includes the re-probe 404
                "last_probe_ts": _time.time() - (HUB_404_REPROBE_S / 2) + 60,
                "skipped_cycles": 0,
                "reprobe_count": 1,
            }
        )
        assert endpoint_sticky() is True, "half-wait must still hold sticky"

        # After the halved wait passes, the re-probe fires again.
        save_state(
            {
                "consecutive_404": HUB_404_STICKY_THRESHOLD + 2,
                "last_probe_ts": _time.time() - (HUB_404_REPROBE_S / 2) - 120,
                "skipped_cycles": 0,
                "reprobe_count": 1,
            }
        )
        out = await _run_with_fetch(monkeypatch, [_err_404()])
        assert out["_calls"]["n"] == 1, "halved TTL expired → real re-probe"
        state = load_state()
        assert state["reprobe_count"] == 2, "failed re-probe increments the counter"

        # A success clears BOTH counters (back to full 24h waits). The failed
        # re-probe refreshed last_probe_ts, so the next cycle correctly
        # sticky-skips; age the probe past the halved wait first.
        state = load_state()
        state["last_probe_ts"] = _time.time() - (HUB_404_REPROBE_S / 2) - 120
        save_state(state)
        await _run_with_fetch(monkeypatch, [_ok()])
        state = load_state()
        assert state["consecutive_404"] == 0
        assert state.get("reprobe_count", 0) == 0

    async def test_non_404_error_resets_not_accumulates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _run_with_fetch(monkeypatch, [_err_404()])
        await _run_with_fetch(monkeypatch, [_err_network()])
        assert load_state()["consecutive_404"] == 0, (
            "network errors say nothing about the endpoint's existence"
        )

    async def test_corrupt_state_fail_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Module-attribute call, NOT a by-name import: the conftest fixture
        # patches hub_health.state_path, and a by-name binding would bypass
        # the patch and write the corrupt fixture into the REAL evolution
        # dir (the exact leak this suite defends against).
        from evolver.gep import hub_health

        hub_health.state_path().write_text("not-json", encoding="utf-8")
        out = await _run_with_fetch(monkeypatch, [_ok()])
        assert out["_calls"]["n"] == 1, "corrupt state must fail open to fetching"
