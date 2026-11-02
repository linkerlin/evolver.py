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


def _host_drops_run_because_error(payload: dict[str, Any]) -> bool:
    """Treat any ``error`` as abandon, unless the preserve flags say keep the run.

    ``next_action`` is ignored on purpose: that is the host this signal is for.
    """
    if not payload.get("error"):
        return False
    if payload.get("abandon_run") is False and payload.get("preserve_pending") is True:
        if payload.get("action_required") == "swarm_solidify":
            return False
    return True


def _host_ticks_only_on_gate_soft_continue(payload: dict[str, Any]) -> bool:
    """Loop while ``gate_soft_continue`` is true. ``ok`` is ignored."""
    return payload.get("gate_soft_continue") is True


def _host_abandons_on_any_error(payload: dict[str, Any]) -> bool:
    """Drop the run whenever ``error`` is set. Preserve flags are ignored."""
    return bool(payload.get("error"))


def _host_dies_when_the_body_looks_failed(payload: dict[str, Any]) -> bool:
    """Treat ``gate_soft_continue=false`` as session death only with a failed body.

    ``ok`` true and no ``error`` is still a live session, even when the flag
    says not to tick.
    """
    if payload.get("ok") is True and not payload.get("error"):
        return False
    return payload.get("gate_soft_continue") is False and payload.get("ok") is False


def _host_ends_session_on_soft_continue_false(payload: dict[str, Any]) -> bool:
    """Any ``gate_soft_continue=false`` ends the session.

    ``session_not_failed=true`` is read first. This host does not look at
    ``ok`` or a missing ``error``. When the flag is true it follows
    ``next_action`` instead of ending the session.
    """
    if payload.get("session_not_failed") is True:
        return False
    return payload.get("gate_soft_continue") is False


def _host_abandons_error_before_preserve_triad(payload: dict[str, Any]) -> bool:
    """Any ``error`` drops the run. The preserve triad is not read by itself.

    ``pending_redirect_loop`` is kept when ``session_not_failed`` is true:
    that flag tells the host to read the triad and follow
    ``action_required``.
    """
    if not payload.get("error"):
        return False
    if payload.get("error") != "pending_redirect_loop":
        return True
    if payload.get("session_not_failed") is not True:
        return True
    if payload.get("preserve_pending") is True and payload.get("abandon_run") is False:
        if payload.get("action_required") == "swarm_solidify":
            return False
    return True


def _assert_session_not_failed(payload: dict[str, Any]) -> None:
    assert payload["session_not_failed"] is True
    assert _host_ends_session_on_soft_continue_false(payload) is False
    assert _host_abandons_error_before_preserve_triad(payload) is False
    assert "session_not_failed" in str(payload.get("note") or "")


def _host_next_call(payload: dict[str, Any]) -> str:
    """Follow ``next_action``. A soft gap is not a hard stop."""
    if payload.get("severity") == "hard" or payload.get("error") in _SOFT_GAPS:
        return "stop"
    action = str(payload.get("next_action") or "")
    if action:
        return action
    if payload.get("gate_soft_continue") is True:
        return "swarm_tick"
    return "stop"


def _steps_invite_another_tick(payload: dict[str, Any]) -> bool:
    """True when a next step tells the host to call ``swarm_tick``."""
    for step in payload.get("next_steps") or []:
        text = str(step)
        lowered = text.lower()
        if "do not call swarm_tick" in lowered:
            continue
        if "swarm_tick" in text or "continue swarm" in lowered:
            return True
    return False


def _assert_solidify_step_first(payload: dict[str, Any]) -> None:
    steps = [str(step) for step in (payload.get("next_steps") or [])]
    assert steps
    assert steps[0].startswith("Call swarm_solidify")
    assert "Parent baseline" in steps[0]
    assert _steps_invite_another_tick(payload) is False


def _assert_preserve_pending(payload: dict[str, Any]) -> None:
    assert payload["preserve_pending"] is True
    assert payload["abandon_run"] is False
    assert payload["action_required"] == "swarm_solidify"
    assert _host_drops_run_because_error(payload) is False


class TestTickSchemaIsOnTheLiveList:
    def test_prompt_mode_and_doctor_are_listed_with_descriptions(self) -> None:
        from evolver.mcp_server import build_server

        tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
        tick = tools["swarm_tick"]
        props = _schema(tick).get("properties") or {}

        assert set(props) >= {
            "agent_name",
            "include_prompt",
            "prompt_mode",
            "checklist_only",
            "supersede_pending",
        }
        supersede = str((props["supersede_pending"] or {}).get("description") or "")
        assert "cycle_started" in supersede
        assert "true" in supersede
        assert "pending_redirect_loop" in supersede
        assert "preserve_pending" in supersede
        assert "abandon_run" in supersede
        assert "gate_soft_continue" in supersede
        assert "session_not_failed" in supersede
        assert props["supersede_pending"].get("default") is False
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
        _assert_preserve_pending(boot)
        _assert_preserve_pending(status)
        # Session start stays soft-continue. The tick redirect is what stops
        # another tick. The step list already names swarm_solidify.
        assert boot.get("gate_soft_continue") is True
        assert status.get("gate_soft_continue") is True
        assert "session_not_failed" not in boot
        assert "session_not_failed" not in status
        assert boot.get("error") not in _SOFT_GAPS
        _assert_solidify_step_first(boot)
        _assert_solidify_step_first(status)
        assert _host_next_call(boot) == "swarm_solidify"
        assert _host_next_call(status) == "swarm_solidify"

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
        assert "preserve_pending" not in boot
        assert "abandon_run" not in boot
        assert "session_not_failed" not in boot
        assert _steps_invite_another_tick(boot) is True
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
        assert "cycle_started=false" in pending
        assert "supersede_pending=true" in pending
        assert "pending_redirect_loop" in pending
        assert "preserve_pending=true" in pending
        assert "abandon_run=false" in pending
        assert "gate_soft_continue=false" in pending
        assert "session_not_failed=true" in pending
        assert "swarm_solidify" in pending
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


class TestPendingTickRedirect:
    async def test_tick_while_pending_does_not_start_a_cycle(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.swarm import swarm_tick

        _write_pending("run_keep")
        state_path = get_solidify_state_path()
        before = state_path.read_text(encoding="utf-8")
        calls = {"n": 0}

        async def boom(is_loop: bool = False) -> dict[str, Any]:
            _ = is_loop
            calls["n"] += 1
            return {"run_id": "should_not", "dispatch_prompt": "nope"}

        monkeypatch.setattr("evolver.evolve.runner._run_single_cycle", boom)
        result = await swarm_tick(agent_name="ignore-next")

        assert calls["n"] == 0
        assert state_path.read_text(encoding="utf-8") == before
        assert result["ok"] is True
        assert result["cycle_started"] is False
        assert result["next_action"] == "swarm_solidify"
        assert result["pending_solidify"] is True
        assert result["run_id"] == "run_keep"
        assert result["dispatch_prompt"] is None
        assert result["dispatch_reason"] == "pending_solidify"
        assert result["redirect_reason"] == "pending_solidify"
        assert result["supersede_pending"] is False
        assert result["redirect_count"] == 1
        assert result["progress"] is False
        assert result["tick_again"] is False
        assert result["tick_closed"] is False
        assert result.get("error") not in _SOFT_GAPS
        assert result.get("error") is None
        _assert_preserve_pending(result)
        _assert_session_not_failed(result)
        assert result.get("gate_soft_continue") is False
        assert _host_ticks_only_on_gate_soft_continue(result) is False
        assert _host_abandons_on_any_error(result) is False
        assert _host_dies_when_the_body_looks_failed(result) is False
        assert _host_next_call(result) == "swarm_solidify"
        _assert_solidify_step_first(result)
        assert "gate_soft_continue is false" in str(result.get("note") or "")
        assert "not a failed session" in str(result.get("note") or "").lower()
        assert result["severity"] == "soft"
        assert result["readonly_smoke"]["settles_run"] is False
        hint = str(result.get("hint") or "")
        assert "swarm_solidify" in hint
        assert "supersede_pending=true" in hint
        assert "not installed" not in hint.lower()
        assert result.get("gap") in _SOFT_GAPS
        assert any("cycle_started=false" in str(item) for item in result.get("warnings") or [])
        assert not (isolated_swarm_env / "evolution" / "swarm_state.json").exists()

    async def test_ready_gate_redirect_stays_soft(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_tick

        _write_pending("run_ready_gate")

        def ready() -> dict[str, Any]:
            return {"armed": True, "baseline": 1.0, "train_ids": ["train-a"]}

        monkeypatch.setattr("evolver.bench.frozen_gate.gate_snapshot", ready)
        result = await swarm_tick()

        assert result["ok"] is True
        assert result["cycle_started"] is False
        assert result["next_action"] == "swarm_solidify"
        assert result["severity"] == "soft"
        assert result.get("error") is None
        assert "gap" not in result
        assert result.get("gate_soft_continue") is not True
        assert "Parent baseline" in str(result.get("note") or "")
        assert result["redirect_count"] == 1
        assert result["progress"] is False
        assert result["tick_closed"] is False
        _assert_preserve_pending(result)
        _assert_session_not_failed(result)
        assert "preserve_pending" in str(result.get("note") or "")
        _assert_solidify_step_first(result)
        assert _host_next_call(result) == "swarm_solidify"
        assert _host_abandons_on_any_error(result) is False

        again = await swarm_tick()
        assert again["ok"] is False
        assert again["error"] == "pending_redirect_loop"
        assert again["severity"] == "soft"
        assert again["retryable"] is False
        assert again["cycle_started"] is False
        assert again["next_action"] == "swarm_solidify"
        assert again["run_id"] == "run_ready_gate"
        assert "gap" not in again
        assert again.get("gate_soft_continue") is not True
        assert "Parent baseline" in str(again.get("note") or "")
        _assert_preserve_pending(again)
        _assert_session_not_failed(again)
        assert _host_ticks_only_on_gate_soft_continue(again) is False

    async def test_repeat_tick_on_the_same_run_closes_without_a_cycle(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host that only checks ``ok`` stops on the second identical tick.

        The first redirect stays soft. The repeat flips ``ok`` with
        ``pending_redirect_loop`` and still does not start a cycle. The soft
        gap stays on ``warning``, not in ``error``. An explicit supersede
        still replaces the run. A different unfinished run starts the count
        over.
        """
        from evolver.gep.paths import get_evolution_dir, get_solidify_state_path
        from evolver.gep.solidify import write_state_for_solidify
        from evolver.swarm import swarm_tick

        _write_pending("run_loop")
        state_path = get_solidify_state_path()
        before = state_path.read_text(encoding="utf-8")
        calls = {"n": 0}

        async def boom(is_loop: bool = False) -> dict[str, Any]:
            _ = is_loop
            calls["n"] += 1
            write_state_for_solidify(
                {
                    "run_id": "run_replaced",
                    "signals": ["log_error"],
                    "selected_gene_id": "g_new",
                    "mutation": {"id": "m_new", "validation": []},
                }
            )
            return {"run_id": "run_replaced", "dispatch_prompt": "started"}

        monkeypatch.setattr("evolver.evolve.runner._run_single_cycle", boom)
        first = await swarm_tick()
        second = await swarm_tick()
        third = await swarm_tick()

        assert calls["n"] == 0
        assert state_path.read_text(encoding="utf-8") == before
        assert not (isolated_swarm_env / "evolution" / "swarm_state.json").exists()
        ledger = get_evolution_dir() / "pending_tick_redirects.json"
        assert json.loads(ledger.read_text(encoding="utf-8")) == {
            "run_id": "run_loop",
            "count": 3,
        }

        assert first["ok"] is True
        assert first.get("error") is None
        assert first["redirect_count"] == 1
        assert first["progress"] is False
        assert first["tick_again"] is False
        assert first["tick_closed"] is False
        assert first["cycle_started"] is False
        assert first["next_action"] == "swarm_solidify"
        assert first["run_id"] == "run_loop"
        _assert_preserve_pending(first)
        _assert_session_not_failed(first)
        assert first.get("gate_soft_continue") is False
        assert _host_ticks_only_on_gate_soft_continue(first) is False
        assert _host_abandons_on_any_error(first) is False
        assert _host_dies_when_the_body_looks_failed(first) is False
        assert _host_next_call(first) == "swarm_solidify"
        _assert_solidify_step_first(first)
        assert "preserve_pending" in str(first.get("note") or "")
        assert "gate_soft_continue is false" in str(first.get("note") or "")

        for closed in (second, third):
            assert closed["ok"] is False
            assert closed["error"] == "pending_redirect_loop"
            assert closed["error"] not in _SOFT_GAPS
            assert closed["severity"] == "soft"
            assert closed["retryable"] is False
            assert closed["tick_closed"] is True
            assert closed["progress"] is False
            assert closed["tick_again"] is False
            assert closed["cycle_started"] is False
            assert closed["pending_solidify"] is True
            assert closed["next_action"] == "swarm_solidify"
            assert closed["run_id"] == "run_loop"
            assert closed["dispatch_prompt"] is None
            assert closed["supersede_pending"] is False
            assert closed.get("gap") in _SOFT_GAPS
            assert closed.get("warning")
            assert closed.get("next_steps")
            assert closed["gate_soft_continue"] is False
            _assert_preserve_pending(closed)
            _assert_session_not_failed(closed)
            assert _host_ticks_only_on_gate_soft_continue(closed) is False
            _assert_solidify_step_first(closed)
            assert _host_next_call(closed) == "swarm_solidify"
            note = str(closed.get("note") or "")
            assert "pending_redirect_loop" in note
            assert "not a gate" in note.lower()
            assert "preserve_pending" in note
            assert "abandon_run" in note
            assert "gate_soft_continue" in note
            assert any(
                "pending_redirect_loop" in str(item) for item in closed.get("warnings") or []
            )
        assert second["redirect_count"] == 2
        assert third["redirect_count"] == 3

        replaced = await swarm_tick(supersede_pending=True)
        assert calls["n"] == 1
        assert replaced["ok"] is True
        assert replaced["cycle_started"] is True
        assert replaced["supersede_pending"] is True
        assert replaced.get("error") != "pending_redirect_loop"
        assert "session_not_failed" not in replaced

        _write_pending("run_other")
        fresh = await swarm_tick()
        assert calls["n"] == 1
        assert fresh["ok"] is True
        assert fresh.get("error") is None
        assert fresh["run_id"] == "run_other"
        assert fresh["redirect_count"] == 1
        assert fresh["cycle_started"] is False
        assert fresh["progress"] is False

    async def test_checkpoint_does_not_burn_the_redirect_count(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.compact_gate import clear_checkpoint, request_checkpoint
        from evolver.gep.paths import get_evolution_dir
        from evolver.swarm import swarm_tick

        calls = {"n": 0}

        async def boom(is_loop: bool = False) -> dict[str, Any]:
            _ = is_loop
            calls["n"] += 1
            return {"run_id": "nope", "dispatch_prompt": "nope"}

        monkeypatch.setattr("evolver.evolve.runner._run_single_cycle", boom)
        _write_pending("run_checkpoint")
        request_checkpoint("precompact_hook")
        blocked = await swarm_tick()
        assert calls["n"] == 0
        assert blocked["next_action"] == "call_swarm_checkpoint_working"
        assert not (get_evolution_dir() / "pending_tick_redirects.json").exists()

        clear_checkpoint()
        opened = await swarm_tick()
        assert calls["n"] == 0
        assert opened["ok"] is True
        assert opened["redirect_count"] == 1
        assert opened.get("error") is None
        _assert_preserve_pending(opened)
        _assert_session_not_failed(opened)
        assert opened.get("gate_soft_continue") is False
        assert _host_ticks_only_on_gate_soft_continue(opened) is False
        assert _host_next_call(opened) == "swarm_solidify"
        _ = isolated_swarm_env

    async def test_supersede_pending_replaces_the_unfinished_run(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.gep.solidify import write_state_for_solidify
        from evolver.swarm import swarm_tick

        _write_pending("run_old")
        calls = {"n": 0}

        async def fake(is_loop: bool = False) -> dict[str, Any]:
            _ = is_loop
            calls["n"] += 1
            write_state_for_solidify(
                {
                    "run_id": "run_new",
                    "signals": ["log_error"],
                    "selected_gene_id": "g_new",
                    "mutation": {"id": "m_new", "validation": []},
                }
            )
            return {
                "run_id": "run_new",
                "cycle_id": "0002",
                "dispatch_prompt": "# GENOME EVOLUTION PROTOCOL\nnew",
                "selected_gene": {"id": "g_new", "name": "N"},
            }

        monkeypatch.setattr("evolver.evolve.runner._run_single_cycle", fake)
        result = await swarm_tick(supersede_pending=True)

        assert calls["n"] == 1
        assert result["ok"] is True
        assert result["cycle_started"] is True
        assert result["supersede_pending"] is True
        assert result["superseded_run_id"] == "run_old"
        assert result["run_id"] == "run_new"
        assert "session_not_failed" not in result
        assert result["dispatch_reason"] == "dispatched"
        assert any("run_old" in str(item) for item in result.get("warnings") or [])
        stored = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        assert stored["last_run"]["run_id"] == "run_new"

    async def test_checkpoint_and_pause_outrank_supersede(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.compact_gate import request_checkpoint
        from evolver.gep.supervision import set_state
        from evolver.swarm import swarm_tick

        calls = {"n": 0}

        async def boom(is_loop: bool = False) -> dict[str, Any]:
            _ = is_loop
            calls["n"] += 1
            return {"run_id": "nope", "dispatch_prompt": "nope"}

        monkeypatch.setattr("evolver.evolve.runner._run_single_cycle", boom)
        _write_pending("run_blocked")
        request_checkpoint("precompact_hook")
        blocked = await swarm_tick(supersede_pending=True)
        assert calls["n"] == 0
        assert blocked["next_action"] == "call_swarm_checkpoint_working"
        assert blocked.get("cycle_started") is not True

        from evolver.gep.compact_gate import clear_checkpoint

        clear_checkpoint()
        set_state(True, by="human", reason="hold")
        paused = await swarm_tick(supersede_pending=True)
        assert calls["n"] == 0
        assert paused["ok"] is True
        assert paused["paused"] is True
        assert paused["cycle_started"] is False
        assert paused["next_action"] == "await_supervisor_resume"


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
    assert "cycle_started" in tick["supersede_pending"]["description"]
    assert "pending_redirect_loop" in tick["supersede_pending"]["description"]
    assert "preserve_pending" in tick["supersede_pending"]["description"]
    assert "abandon_run" in tick["supersede_pending"]["description"]
    assert "session_not_failed" in tick["supersede_pending"]["description"]
    assert tick["supersede_pending"]["default"] is False
    assert tools["swarm_doctor"]["annotations"]["readOnlyHint"] is True
    assert json.dumps(tools["swarm_tick"]["description"]).count("\\n        ") == 0
