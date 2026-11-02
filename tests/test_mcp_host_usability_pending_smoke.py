"""Pending-run boot guidance, and the live tools/list contract for short tick.

``tools/list`` already publishes ``prompt_mode``, ``checklist_only``, and
``swarm_doctor``. A host catalog that still shows only ``agent_name`` and
``include_prompt`` is a stale client session, not a missing registration.

A prior unfinished run keeps ``next_action=swarm_solidify``. The soft-gap
essay must not replace that hint: a read-only smoke uses ``swarm_doctor`` /
``swarm_status`` and does not settle the run or weaken the gate.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

_SOFT_GAPS = frozenset({"pack_absent", "no_baseline", "unmeasured"})


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point swarm state at tmp_path so a boot cannot touch the real tree."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    monkeypatch.setattr("evolver.config.SWARM_GATE_HANDOFF", "hotl")
    return tmp_path


def _schema(tool: Any) -> dict[str, Any]:
    raw = tool.input_schema
    if isinstance(raw, dict):
        return raw
    dumped = raw.model_dump()
    assert isinstance(dumped, dict)
    return dumped


def _write_pending(run_id: str = "run_pending_smoke") -> None:
    from evolver.gep.solidify import write_state_for_solidify

    write_state_for_solidify(
        {
            "run_id": run_id,
            "signals": ["log_error"],
            "selected_gene_id": "g_smoke",
            "mutation": {"id": "m_smoke", "validation": []},
        }
    )


class TestTickSchemaIsOnTheLiveList:
    def test_prompt_mode_and_doctor_are_listed_with_descriptions(self) -> None:
        from evolver.mcp_server import build_server

        tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
        tick = tools["swarm_tick"]
        props = _schema(tick).get("properties") or {}

        assert set(props) >= {"agent_name", "include_prompt", "prompt_mode", "checklist_only"}
        mode = props["prompt_mode"]
        assert mode.get("enum") == ["full", "short"]
        assert "short" in str(mode.get("description") or "")
        assert "full" in str(mode.get("description") or "")
        checklist = str((props["checklist_only"] or {}).get("description") or "")
        assert "short" in checklist
        description = tick.description or ""
        assert "prompt_mode=short" in description
        assert "\n        " not in description

        doctor = tools["swarm_doctor"]
        assert doctor.annotations is not None
        assert doctor.annotations.read_only_hint is True
        assert "fix" not in (_schema(doctor).get("properties") or {})


class TestPendingBootSmokeHint:
    def test_pending_boot_keeps_solidify_and_names_a_read_only_smoke(
        self, isolated_swarm_env: Path
    ) -> None:
        from evolver.swarm import swarm_boot, swarm_doctor, swarm_status

        _write_pending()
        boot = swarm_boot("smoke-host")

        assert boot["ok"] is True
        assert boot["next_action"] == "swarm_solidify"
        assert boot["pending_solidify"] is True
        assert boot["boot_once"] == []
        assert boot.get("error") not in _SOFT_GAPS
        assert boot.get("severity") == "soft"
        assert boot.get("gap") in _SOFT_GAPS
        hint = str(boot.get("hint") or "")
        assert "swarm_solidify" in hint
        assert "swarm_doctor" in hint
        smoke = boot["readonly_smoke"]
        assert smoke["safe"] is True
        assert smoke["settles_run"] is False
        assert smoke["tools"] == ["swarm_doctor", "swarm_status"]
        # The soft-gap essay stays on warning. It must not replace this hint.
        assert "not installed" not in hint.lower()
        assert "may proceed" not in hint
        assert boot.get("warning")

        doctor = swarm_doctor()
        assert doctor["read_only"] is True
        status = swarm_status()
        assert status["pending_solidify"] is True
        assert status["next_action"] == "swarm_solidify"
        assert status["readonly_smoke"]["settles_run"] is False
        assert status["readonly_smoke"]["tools"] == smoke["tools"]

    def test_soft_boot_without_a_pending_run_does_not_grow_a_smoke_block(
        self, isolated_swarm_env: Path
    ) -> None:
        from evolver.swarm import swarm_boot

        boot = swarm_boot("plain-host")
        assert boot["next_action"] == "swarm_tick"
        assert boot.get("pending_solidify") is not True
        assert "readonly_smoke" not in boot
        assert boot.get("severity") == "soft"
        assert boot.get("gate_soft_continue") is True
        hint = str(boot.get("hint") or "")
        assert "recommended" in hint or "Soft-accept" in hint or "soft-continue" in hint

    def test_checkpoint_outranks_the_smoke_block(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.compact_gate import request_checkpoint
        from evolver.swarm import swarm_boot

        _write_pending()
        request_checkpoint("precompact_hook")
        boot = swarm_boot("checkpoint-host")
        assert boot["next_action"] == "call_swarm_checkpoint_working"
        assert "readonly_smoke" not in boot
        state = boot.get("state")
        assert isinstance(state, dict)
        assert "readonly_smoke" not in state

    def test_instrument_names_the_read_only_alternative_only_while_pending(self) -> None:
        from evolver.swarm import build_instrument_prompt

        pending = build_instrument_prompt(
            {"agent_name": "a", "workspace_root": "/ws", "pending_solidify": True}
        )
        assert "先调用 `swarm_solidify`" in pending
        assert "只读冒烟" in pending
        assert "swarm_doctor" in pending
        assert "await_supervisor_resume" not in pending

        ready = build_instrument_prompt(
            {
                "agent_name": "a",
                "workspace_root": "/ws",
                "bench_pack_gate": {"armed": True, "baseline": 1.0, "train_ids": ["train-a"]},
            }
        )
        assert "调用 `swarm_tick` 开始第一轮进化" in ready
        assert "只读冒烟" not in ready


def test_wire_tools_list_publishes_prompt_mode(tmp_path: Path) -> None:
    """The stdio ``tools/list`` frame, not the in-process object, carries the params."""
    from tests.test_mcp_protocol import _McpClient

    client = _McpClient(tmp_path)
    try:
        client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = {t["name"]: t for t in client.request("tools/list")["result"]["tools"]}
    finally:
        client.close()

    tick = tools["swarm_tick"]["inputSchema"]["properties"]
    assert tick["prompt_mode"]["enum"] == ["full", "short"]
    assert "short" in tick["prompt_mode"]["description"]
    assert "short" in tick["checklist_only"]["description"]
    assert tools["swarm_doctor"]["annotations"]["readOnlyHint"] is True
    assert json.dumps(tools["swarm_tick"]["description"]).count("\\n        ") == 0
