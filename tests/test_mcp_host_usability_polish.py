"""MCP polish invariants: bounded engine_log on evolve_begin and list envelopes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

_ENVELOPE_KEYS = frozenset({"ok", "items", "hint"})


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    return tmp_path


def _tool_payload(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None) or []
    if not content:
        pytest.fail(f"tool returned an empty payload: {result!r}")
    payload = json.loads(content[0].text)
    assert isinstance(payload, dict)
    return payload


def test_list_tools_use_consistent_envelope(isolated_swarm_env: Path) -> None:
    from evolver.mcp_server import build_server

    server = build_server()
    for name, args in (
        ("tool_asset_search", {"query": "none"}),
        ("tool_cycle_timeline", {"limit": 5}),
    ):
        payload = _tool_payload(asyncio.run(server.call_tool(name, args)))
        assert payload["ok"] is True
        assert payload["items"] == []
        assert set(payload) >= _ENVELOPE_KEYS


async def test_evolve_begin_bounds_engine_log(isolated_swarm_env: Path) -> None:
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.swarm import evolve_begin

    result = await evolve_begin(hypothesis="Verify bounded engine log in evolve_begin")
    assert result["ok"] is True
    assert result["fsm_state"] == "ACTIVE_RUN"
    assert len(str(result.get("engine_log") or "")) <= SWARM_TICK_LOG_MAX_CHARS
