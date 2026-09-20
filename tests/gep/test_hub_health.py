"""Tests for evolver.gep.hub_health + hub_client sticky preflight (round-46)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.hub_health import (
    HUB_404_STICKY_THRESHOLD,
    endpoint_sticky,
    load_state,
    note_404,
    reset_404,
)


class TestHubHealth:
    def test_endpoint_sticky_after_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        from evolver.gep.hub_health import save_state

        state = load_state()
        for _ in range(HUB_404_STICKY_THRESHOLD):
            state = note_404(state)
        save_state(state)  # note_404 is in-memory; sticky reads from disk
        import time

        # last_probe_ts is now — sticky must hold.
        assert endpoint_sticky() is True
        # TTL-expired probe window fails the sticky check (ancient ts).
        state["last_probe_ts"] = time.time() - 10**9
        (tmp_path / "hub_endpoint_state.json").write_text(json.dumps(state), encoding="utf-8")
        assert endpoint_sticky() is False

    def test_below_threshold_not_sticky(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        (tmp_path / "hub_endpoint_state.json").write_text(
            json.dumps({"consecutive_404": HUB_404_STICKY_THRESHOLD - 1, "last_probe_ts": 1e12}),
            encoding="utf-8",
        )
        assert endpoint_sticky() is False

    def test_reset_clears_counter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        state = reset_404({"consecutive_404": 3, "last_probe_ts": 1e12})
        assert state["consecutive_404"] == 0
        assert endpoint_sticky() is False


class TestHubClientPreflight:
    async def test_sticky_skips_http_entirely(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time

        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
        (tmp_path / "hub_endpoint_state.json").write_text(
            json.dumps(
                {
                    "consecutive_404": HUB_404_STICKY_THRESHOLD,
                    "last_probe_ts": time.time(),
                }
            ),
            encoding="utf-8",
        )
        from evolver.atp import hub_client

        def _no_client(*args: object, **kwargs: object) -> None:
            raise AssertionError("sticky preflight must not construct an HTTP client")

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _no_client)
        result = await hub_client.list_my_tasks()
        assert result["ok"] is False
        assert result["error"] == "hub_endpoint_missing"

    async def test_not_sticky_proceeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))  # no state file → not sticky
        from evolver.atp import hub_client

        calls = {"n": 0}

        class _FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, object]:
                return {"tasks": []}

        class _FakeClient:
            def __init__(self, *a: object, **kw: object) -> None:
                pass

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *a: object) -> None:
                pass

            async def get(self, *a: object, **kw: object) -> _FakeResp:
                calls["n"] += 1
                return _FakeResp()

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _FakeClient)
        result = await hub_client.list_my_tasks()
        assert calls["n"] == 1, "non-sticky must hit HTTP as before"
        assert result["ok"] is True
