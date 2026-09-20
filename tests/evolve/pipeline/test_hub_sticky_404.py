"""Tests for hub-phase sticky 404 short-circuit (round-45)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.evolve.pipeline import hub as hub_mod
from evolver.evolve.pipeline.hub import HUB_404_STICKY_THRESHOLD, hub_phase


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
    async def test_three_404s_then_sticky_skip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
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

    async def test_ttl_expiry_reprobes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        state_path = tmp_path / "hub_endpoint_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "consecutive_404": HUB_404_STICKY_THRESHOLD,
                    "last_probe_ts": 0.0,  # ancient → TTL expired
                    "skipped_cycles": 99,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = await _run_with_fetch(monkeypatch, [_ok()])
        assert out["_calls"]["n"] == 1, "expired TTL must re-probe"
        assert out["hub_hit"]["reason"] == "no_tasks"

    async def test_success_resets_counter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        (tmp_path / "hub_endpoint_state.json").write_text(
            json.dumps({"consecutive_404": 2, "last_probe_ts": 1.0e12, "skipped_cycles": 0}),
            encoding="utf-8",
        )
        await _run_with_fetch(monkeypatch, [_ok()])
        data = json.loads((tmp_path / "hub_endpoint_state.json").read_text(encoding="utf-8"))
        assert data["consecutive_404"] == 0

    async def test_non_404_error_resets_not_accumulates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        await _run_with_fetch(monkeypatch, [_err_404()])
        await _run_with_fetch(monkeypatch, [_err_network()])
        data = json.loads((tmp_path / "hub_endpoint_state.json").read_text(encoding="utf-8"))
        assert data["consecutive_404"] == 0, (
            "network errors say nothing about the endpoint's existence"
        )

    async def test_corrupt_state_fail_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        (tmp_path / "hub_endpoint_state.json").write_text("not-json", encoding="utf-8")
        out = await _run_with_fetch(monkeypatch, [_ok()])
        assert out["_calls"]["n"] == 1, "corrupt state must fail open to fetching"
