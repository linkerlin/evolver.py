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
import subprocess
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


def _host_ticks_unless_retryable_is_false(payload: dict[str, Any]) -> bool:
    """Keep ticking unless ``retryable`` is strict false.

    An omitted ``retryable`` counts as continue. ``tick_again``,
    ``next_action``, and ``ok`` are ignored. An omitted
    ``gate_soft_continue`` is not a stop. Strict false of that flag would
    stop this host too, and would also end the session for a host that
    treats that false as death, so the redirect must not set it.
    """
    if payload.get("gate_soft_continue") is False:
        return False
    return payload.get("retryable") is not False


def _host_dies_on_nonretryable_failed_ok(payload: dict[str, Any]) -> bool:
    """``retryable=false`` ends the session only together with ``ok`` false.

    The first redirect stays ``ok`` true, so this host does not die there.
    ``session_not_failed`` is ignored on purpose.
    """
    return payload.get("retryable") is False and payload.get("ok") is False


def _host_abandons_on_any_error(payload: dict[str, Any]) -> bool:
    """Drop the run whenever ``error`` is set. Preserve flags are ignored."""
    return bool(payload.get("error"))


def _host_dies_on_soft_continue_false_ignoring_new_flags(payload: dict[str, Any]) -> bool:
    """Strict ``gate_soft_continue=false`` ends the session.

    ``session_not_failed``, ``ok``, ``tick_again``, and ``next_action`` are
    ignored. A missing flag is not false, so the session stays up.
    """
    return payload.get("gate_soft_continue") is False


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


def _host_solidifies_only_if_error_is_the_fuse(payload: dict[str, Any]) -> bool:
    """Solidify only when ``error`` is the old fuse code.

    ``loop_fuse``, ``redirect_reason``, and ``next_action`` are ignored.
    The fuse no longer sets ``error``, so this host misses it.
    """
    return payload.get("error") == "pending_redirect_loop"


def _host_solidifies_when_it_reads_the_fuse(payload: dict[str, Any]) -> bool:
    """Solidify from ``loop_fuse`` or the fuse ``redirect_reason``.

    A bare ``pending_redirect_loop`` is not a ``next_action``. ``error`` is
    not consulted. The first redirect has neither fuse field.
    """
    if payload.get("loop_fuse") == "pending_redirect_loop":
        return True
    return payload.get("redirect_reason") == "pending_redirect_loop"


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


def _host_ticks_unless_tick_again_is_false(payload: dict[str, Any]) -> bool:
    """Keep ticking unless ``tick_again`` is strict false.

    ``next_action``, ``ok``, ``retryable``, and ``soft_continue`` are ignored.
    An omitted ``tick_again`` counts as continue. ``soft_continue=true`` is
    not rewritten, and ``gate_soft_continue`` is not consulted.
    """
    return payload.get("tick_again") is not False


def _host_ticks_only_on_soft_continue(payload: dict[str, Any]) -> bool:
    """Tick while ``soft_continue`` is true.

    ``tick_again``, ``next_action``, ``ok``, and ``retryable`` are ignored.
    This host is the residual that a false ``soft_continue`` would stop, and
    that false is not allowed on a soft gap.
    """
    return payload.get("soft_continue") is True


def _host_smoke_decides_without_next_action(payload: dict[str, Any]) -> str:
    """What a smoke host does after ``swarm_doctor``.

    ``next_action`` wins. With no action, ``soft_continue`` or ``ok`` true
    means the loop is not blocked, so the host ticks. An omitted
    ``gate_soft_continue`` is not a stop. ``session_not_failed`` is ignored:
    doctor must not need that tick-redirect flag.
    """
    action = str(payload.get("next_action") or "")
    if action:
        return action
    if payload.get("soft_continue") is True or payload.get("ok") is True:
        return "swarm_tick"
    return "stop"


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


def _assert_doctor_fix_deferred(payload: dict[str, Any]) -> None:
    """Soft solidify steer: setup commands are not the current step.

    ``evolver doctor --fix``, ``evolver bench freeze``, and
    ``evolver bench baseline`` stay off ``commands`` and ``fixes``.
    The preserve triad still names solidify.
    """
    assert _checklist_runs_doctor_fix_now(payload) is False
    assert _checklist_runs_bench_setup_now(payload) is False
    commands = [str(item).strip() for item in payload.get("commands") or []]
    fixes = [str(item).strip() for item in payload.get("fixes") or []]
    assert "evolver doctor --fix" not in commands
    assert "evolver bench freeze" not in commands
    assert "evolver bench baseline" not in commands
    assert "evolver bench freeze" not in fixes
    assert "evolver bench baseline" not in fixes
    gap = payload.get("gap")
    if gap in ("pack_absent", "no_baseline", "unmeasured"):
        steps = [str(step).lower() for step in payload.get("next_steps") or []]
        assert any("before solidify" in step for step in steps)
        assert not any(
            "evolver bench freeze" in step and "do not run" not in step for step in steps
        )
        assert not any(
            "evolver bench baseline" in step and "do not run" not in step for step in steps
        )
    assert payload.get("action_required") == "swarm_solidify"
    assert payload.get("preserve_pending") is True
    assert payload.get("abandon_run") is False


def _checklist_runs_bench_setup_now(payload: dict[str, Any]) -> bool:
    """True when a list offers freeze or baseline as the current step."""
    for key in ("fixes", "commands"):
        for item in payload.get(key) or []:
            text = str(item).strip()
            if text in ("evolver bench freeze", "evolver bench baseline"):
                return True
    for step in payload.get("next_steps") or []:
        text = str(step)
        lowered = text.lower()
        if "evolver bench freeze" not in text and "evolver bench baseline" not in text:
            continue
        if "do not run" in lowered and "before solidify" in lowered:
            continue
        return True
    return False


def _checklist_runs_doctor_fix_now(payload: dict[str, Any]) -> bool:
    """True when a list offers ``evolver doctor --fix`` as the current step.

    Exact entries in ``fixes`` or ``commands`` count. A next step that names
    the command counts unless it says not to run it before solidify.
    """
    for key in ("fixes", "commands"):
        for item in payload.get(key) or []:
            if str(item).strip() == "evolver doctor --fix":
                return True
    for step in payload.get("next_steps") or []:
        text = str(step)
        if "evolver doctor --fix" not in text:
            continue
        if "do not run evolver doctor --fix before solidify" in text.lower():
            continue
        return True
    return False


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


def _assert_stop_is_not_failure(payload: dict[str, Any], *, closed: bool, gap: bool) -> None:
    """Stop-tick signals stay off the fail and abandon fields.

    A soft gap omits ``gate_soft_continue`` and never writes false, so a host
    that dies on strict false stays up. A host that loops only while the flag
    is true does not tick. ``soft_gap.advisory`` stays true and
    ``soft_gap.tick`` is false. Boot and status keep the true bit. Stop-tick
    stays on ``tick_again``, ``retryable``, and ``soft_gap.tick``. Without a
    soft gap the key stays absent and ``soft_gap`` is absent.
    The fuse code lives in ``loop_fuse``. ``error`` is absent, so a host that
    abandons on any error keeps the run. ``ok`` is still false on the fuse.
    """
    assert payload.get("gate_soft_continue") is not False
    assert "error" not in payload
    assert payload.get("tick_again") is False
    assert _host_ticks_unless_tick_again_is_false(payload) is False
    assert payload.get("retryable") is False
    assert "retryable=false" in str(payload.get("note") or "")
    assert _host_ticks_unless_retryable_is_false(payload) is False
    if not closed:
        assert _host_dies_on_nonretryable_failed_ok(payload) is False
    assert _host_dies_on_soft_continue_false_ignoring_new_flags(payload) is False
    assert _host_ends_session_on_soft_continue_false(payload) is False
    assert _host_abandons_on_any_error(payload) is False
    assert _host_abandons_error_before_preserve_triad(payload) is False
    note = str(payload.get("note") or "")
    assert payload["dispatch_reason"] == "pending_solidify"
    assert payload["next_action"] == "swarm_solidify"
    assert payload["next_action"] != "pending_redirect_loop"
    if closed:
        assert payload["ok"] is False
        assert payload["loop_fuse"] == "pending_redirect_loop"
        assert payload["redirect_reason"] == "pending_redirect_loop"
        assert payload["retryable"] is False
        assert "error" not in payload
        assert "loop_fuse" in note
        assert "redirect_reason=pending_redirect_loop" in note
        assert "pending_redirect_loop" in note
        assert _host_solidifies_only_if_error_is_the_fuse(payload) is False
        assert _host_solidifies_when_it_reads_the_fuse(payload) is True
    else:
        assert payload["ok"] is True
        assert "loop_fuse" not in payload
        assert payload["redirect_reason"] == "pending_solidify"
        assert _host_solidifies_only_if_error_is_the_fuse(payload) is False
        assert _host_solidifies_when_it_reads_the_fuse(payload) is False
    if gap:
        assert "gate_soft_continue" not in payload
        assert payload.get("gate_soft_continue") is not False
        assert _host_ticks_only_on_gate_soft_continue(payload) is False
        soft_gap = payload["soft_gap"]
        assert soft_gap["present"] is True
        assert soft_gap["advisory"] is True
        assert soft_gap["tick"] is False
        assert soft_gap["code"] == payload.get("gap")
        assert "soft_gap.tick=false" in note
        assert "not a failed session" in note.lower()
        assert "not a license to tick" in note
    else:
        assert "gate_soft_continue" not in payload
        assert "soft_gap" not in payload
        assert _host_ticks_only_on_gate_soft_continue(payload) is False


def test_standing_instructions_name_the_fuse_not_a_bare_code() -> None:
    """Connect-time text names ``loop_fuse``, not a bare peer of ``next_action``."""
    from evolver.mcp_server import standing_instructions

    text = standing_instructions()
    assert len(text) < 1200
    assert "loop_fuse=pending_redirect_loop" in text
    assert " or pending_redirect_loop" not in text
    assert "error=pending_redirect_loop" not in text
    assert "next_action=pending_redirect_loop" not in text
    assert "next_action=swarm_solidify or loop_fuse=pending_redirect_loop" in text


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
        assert "loop_fuse" in supersede
        assert "redirect_reason=pending_redirect_loop" in supersede
        assert "error=pending_redirect_loop" not in supersede
        assert "next_action=pending_redirect_loop" not in supersede
        assert "preserve_pending" in supersede
        assert "abandon_run" in supersede
        assert "gate_soft_continue=true" in supersede
        assert "never writes gate_soft_continue=false" in supersede
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
        joined = " ".join(description.split())
        assert "does not list evolver doctor --fix" in joined
        assert "evolver bench freeze" in joined
        assert "evolver bench baseline" in joined
        assert "as the current step" in joined

        doctor = tools["swarm_doctor"]
        assert doctor.annotations is not None
        assert doctor.annotations.read_only_hint is True
        assert "fix" not in (_schema(doctor).get("properties") or {})
        description = " ".join((doctor.description or "").split())
        assert "swarm_solidify" in description
        assert "Parent baseline" in description
        assert "session_not_failed" in description
        assert "tick_again=false" in description
        assert "does not list evolver doctor --fix" in description
        assert "evolver bench baseline" in description
        assert "as a current step" in description

        boot_desc = " ".join((tools["swarm_boot"].description or "").split())
        status_desc = " ".join((tools["swarm_status"].description or "").split())
        assert "tick_again=false" in boot_desc
        assert "gate_soft_continue" in boot_desc
        assert "tick_again=false" in status_desc
        assert "gate_soft_continue" in status_desc
        for text in (boot_desc, status_desc):
            assert "does not list evolver doctor --fix" in text
            assert "evolver bench freeze" in text
            assert "as a current step" in text


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
        # Soft gap stays gate_soft_continue=true. tick_again=false stops a
        # host that only halts on strict false. A host that loops only while
        # gate_soft_continue is true still ticks; do not flip that flag.
        state = boot["state"]
        assert isinstance(state, dict)
        assert boot["tick_again"] is False
        assert status["tick_again"] is False
        assert state["tick_again"] is False
        assert _host_ticks_unless_tick_again_is_false(boot) is False
        assert _host_ticks_unless_tick_again_is_false(status) is False
        assert _host_ticks_unless_tick_again_is_false(state) is False
        assert _host_ticks_only_on_gate_soft_continue(boot) is True
        assert _host_ticks_only_on_gate_soft_continue(status) is True
        assert boot.get("gate_soft_continue") is True
        assert status.get("gate_soft_continue") is True
        assert state.get("gate_soft_continue") is True
        assert "session_not_failed" not in boot
        assert "session_not_failed" not in status
        assert "session_not_failed" not in state
        assert "loop_fuse" not in boot
        assert "loop_fuse" not in status
        assert boot.get("redirect_reason") != "pending_redirect_loop"
        assert status.get("redirect_reason") != "pending_redirect_loop"
        assert boot.get("error") not in _SOFT_GAPS
        _assert_solidify_step_first(boot)
        _assert_solidify_step_first(status)
        assert _host_next_call(boot) == "swarm_solidify"
        assert _host_next_call(status) == "swarm_solidify"
        # Command lists are the checklist. doctor --fix is not the current step.
        assert _checklist_runs_doctor_fix_now(boot) is False
        assert _checklist_runs_doctor_fix_now(status) is False
        assert _checklist_runs_doctor_fix_now(state) is False
        assert _checklist_runs_bench_setup_now(boot) is False
        assert _checklist_runs_bench_setup_now(status) is False
        assert _checklist_runs_bench_setup_now(state) is False
        assert "soft_gap" not in boot
        assert "soft_gap" not in status

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
        assert "tick_again" not in boot
        assert "preserve_pending" not in boot
        assert "abandon_run" not in boot
        assert "session_not_failed" not in boot
        assert _steps_invite_another_tick(boot) is True
        hint = str(boot.get("hint") or "")
        assert "recommended" in hint or "Soft-accept" in hint or "soft-continue" in hint
        # No unfinished run: doctor --fix and bench setup stay listed.
        assert _checklist_runs_doctor_fix_now(boot) is True
        assert "evolver bench freeze" in boot.get("commands") or []

    def test_checkpoint_outranks_the_smoke_block(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.compact_gate import request_checkpoint
        from evolver.swarm import swarm_boot

        _write_pending()
        request_checkpoint("precompact_hook")
        boot = swarm_boot("checkpoint-host")
        assert boot["next_action"] == "call_swarm_checkpoint_working"
        assert "readonly_smoke" not in boot
        assert "tick_again" not in boot
        state = boot.get("state")
        assert isinstance(state, dict)
        assert "readonly_smoke" not in state
        assert "tick_again" not in state

    def test_pending_doctor_on_a_soft_gap_names_solidify(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read-only smoke must steer to solidify, not back into tick.

        ``readonly_smoke`` names ``swarm_doctor`` next to ``swarm_status``.
        Status already sets ``next_action=swarm_solidify``. Doctor used to
        return only ``soft_continue`` and a hint that the loop is not blocked,
        so a host that smokes and then follows ``next_action`` (or ticks when
        that key is missing and ``soft_continue`` is true) never solidifies.
        A host that ignores ``next_action`` and stops only on strict
        ``tick_again=false`` still ticks while that key is omitted.
        ``soft_continue`` stays true. The first tick redirect and the fuse
        already set ``tick_again`` false.
        """
        from evolver.bench.frozen_gate import baseline_path, frozen_pack_path
        from evolver.swarm import swarm_doctor

        monkeypatch.delenv("EVOLVER_NO_PARENT_GIT", raising=False)
        subprocess.run(["git", "init"], cwd=isolated_swarm_env, check=True, capture_output=True)

        idle = swarm_doctor()
        assert idle["ok"] is True
        assert idle["soft_continue"] is True
        assert "next_action" not in idle
        assert "pending_solidify" not in idle
        assert "preserve_pending" not in idle
        assert "session_not_failed" not in idle
        assert "gate_soft_continue" not in idle
        assert "tick_again" not in idle
        assert _checklist_runs_doctor_fix_now(idle) is True
        assert "evolver bench freeze" in idle["fixes"]

        _write_pending("run_doctor_soft")
        report = swarm_doctor()

        assert report["ok"] is True
        assert report["soft_continue"] is True
        assert report["loop_ready"] is False
        assert report["read_only"] is True
        assert report["blockers"] == []
        assert report["pending_solidify"] is True
        assert report["next_action"] == "swarm_solidify"
        assert report["tick_again"] is False
        assert report["readonly_smoke"]["settles_run"] is False
        assert report["readonly_smoke"]["tools"] == ["swarm_doctor", "swarm_status"]
        _assert_preserve_pending(report)
        assert "session_not_failed" not in report
        assert "gate_soft_continue" not in report
        assert "soft_gap" not in report
        assert report.get("error") not in _SOFT_GAPS
        assert _host_dies_on_soft_continue_false_ignoring_new_flags(report) is False
        assert _host_smoke_decides_without_next_action(report) == "swarm_solidify"
        assert _host_ticks_unless_tick_again_is_false(report) is False
        # soft_continue stays the soft-gap bit. Hosts that ignore tick_again
        # and only read it still tick. Do not flip it to false.
        assert _host_ticks_only_on_soft_continue(report) is True
        hint = str(report.get("hint") or "")
        assert hint.startswith("Call swarm_solidify")
        assert "Do not call swarm_tick" in hint
        assert "tick_again=false" in hint
        assert "Parent baseline" in hint
        assert "Do not apply fixes before swarm_solidify" in hint
        assert "does not list `evolver doctor --fix`" in hint
        assert "`evolver bench freeze`" in hint
        assert "`evolver bench baseline`" in hint
        assert "as a current step" in hint
        assert "do not run evolver doctor --fix before solidify" in hint.lower()
        assert (
            "do not run evolver bench freeze or evolver bench baseline before solidify"
            in hint.lower()
        )
        assert "does not execute" in hint
        assert "not installed" in hint.lower() or "do not block the loop" in hint.lower()
        assert not baseline_path().exists()
        assert not frozen_pack_path().exists()
        assert _checklist_runs_doctor_fix_now(report) is False
        assert report["action_required"] == "swarm_solidify"

    def test_pending_doctor_hard_blocker_does_not_invent_solidify(
        self, isolated_swarm_env: Path
    ) -> None:
        """A hard doctor failure stays a hard stop. No solidify action is added.

        The isolated tree is not a git repo, so ``ok`` is false. That must
        not grow ``next_action``, ``gate_soft_continue``,
        ``session_not_failed``, or ``tick_again``.
        """
        from evolver.swarm import swarm_doctor

        _write_pending("run_doctor_hard")
        report = swarm_doctor()
        assert report["ok"] is False
        assert report["soft_continue"] is False
        assert report["read_only"] is True
        assert "next_action" not in report
        assert "pending_solidify" not in report
        assert "session_not_failed" not in report
        assert "gate_soft_continue" not in report
        assert "tick_again" not in report
        assert _host_smoke_decides_without_next_action(report) == "stop"
        _ = isolated_swarm_env

    def test_instrument_names_the_read_only_alternative_only_while_pending(self) -> None:
        from evolver.swarm import build_instrument_prompt

        pending = build_instrument_prompt(
            {"agent_name": "a", "workspace_root": "/ws", "pending_solidify": True}
        )
        assert "先调用 `swarm_solidify`" in pending
        assert "不把 `evolver doctor --fix` 当当前步骤" in pending
        assert "tick 与保险丝的 `commands` 和 `next_steps`" in pending
        assert "只读冒烟" in pending
        assert "swarm_doctor" in pending
        assert "cycle_started=false" in pending
        assert "supersede_pending=true" in pending
        assert "pending_redirect_loop" in pending
        assert "preserve_pending=true" in pending
        assert "abandon_run=false" in pending
        assert "loop_fuse=pending_redirect_loop" in pending
        assert "redirect_reason=pending_redirect_loop" in pending
        assert "gate_soft_continue=true" in pending
        assert "soft_gap.tick=false" in pending
        assert "不写这个键" in pending
        assert "error=pending_redirect_loop" not in pending
        assert "next_action=pending_redirect_loop" not in pending
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
        _assert_stop_is_not_failure(result, closed=False, gap=True)
        assert _host_dies_when_the_body_looks_failed(result) is False
        assert _host_next_call(result) == "swarm_solidify"
        _assert_solidify_step_first(result)
        assert result["severity"] == "soft"
        assert result["readonly_smoke"]["settles_run"] is False
        hint = str(result.get("hint") or "")
        assert "swarm_solidify" in hint
        assert "supersede_pending=true" in hint
        assert "not installed" not in hint.lower()
        assert result.get("gap") in _SOFT_GAPS
        assert any("cycle_started=false" in str(item) for item in result.get("warnings") or [])
        # Soft-gap solidify steer: setup commands are not the current step.
        # The continue flag is absent, never false. soft_gap says do not tick.
        _assert_doctor_fix_deferred(result)
        assert "gate_soft_continue" not in result
        assert result["soft_gap"]["tick"] is False
        assert result.get("soft_continue") is not False
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
        assert "gap" not in result
        assert "Parent baseline" in str(result.get("note") or "")
        assert result["redirect_count"] == 1
        assert result["progress"] is False
        assert result["tick_closed"] is False
        _assert_preserve_pending(result)
        _assert_session_not_failed(result)
        _assert_stop_is_not_failure(result, closed=False, gap=False)
        assert "preserve_pending" in str(result.get("note") or "")
        _assert_solidify_step_first(result)
        assert _host_next_call(result) == "swarm_solidify"
        assert _checklist_runs_doctor_fix_now(result) is False

        again = await swarm_tick()
        assert again["severity"] == "soft"
        assert again["cycle_started"] is False
        assert again["next_action"] == "swarm_solidify"
        assert again["run_id"] == "run_ready_gate"
        assert "gap" not in again
        assert "Parent baseline" in str(again.get("note") or "")
        _assert_preserve_pending(again)
        _assert_session_not_failed(again)
        _assert_stop_is_not_failure(again, closed=True, gap=False)

    async def test_repeat_tick_on_the_same_run_closes_without_a_cycle(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host that only checks ``ok`` stops on the second identical tick.

        The first redirect stays soft. The repeat flips ``ok`` and sets
        ``loop_fuse=pending_redirect_loop`` with no ``error`` field, and still
        does not start a cycle. The soft gap stays on ``warning``. An explicit
        supersede still replaces the run. A different unfinished run starts
        the count over.
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
        _assert_doctor_fix_deferred(first)
        assert "gate_soft_continue" not in first
        assert first["soft_gap"]["advisory"] is True
        assert first["progress"] is False
        assert first["tick_again"] is False
        assert first["tick_closed"] is False
        assert first["cycle_started"] is False
        assert first["next_action"] == "swarm_solidify"
        assert first["run_id"] == "run_loop"
        _assert_preserve_pending(first)
        _assert_session_not_failed(first)
        _assert_stop_is_not_failure(first, closed=False, gap=True)
        assert _host_dies_when_the_body_looks_failed(first) is False
        assert _host_next_call(first) == "swarm_solidify"
        _assert_solidify_step_first(first)
        assert "preserve_pending" in str(first.get("note") or "")

        for closed in (second, third):
            assert closed["severity"] == "soft"
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
            _assert_preserve_pending(closed)
            _assert_session_not_failed(closed)
            _assert_stop_is_not_failure(closed, closed=True, gap=True)
            _assert_solidify_step_first(closed)
            assert _host_next_call(closed) == "swarm_solidify"
            _assert_doctor_fix_deferred(closed)
            assert "gate_soft_continue" not in closed
            assert closed["soft_gap"]["tick"] is False
            assert closed.get("soft_continue") is not False
            assert closed["ok"] is False
            note = str(closed.get("note") or "")
            assert "not a gate" in note.lower()
            assert "preserve_pending" in note
            assert "abandon_run" in note
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
        assert "loop_fuse" not in replaced
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
        _assert_stop_is_not_failure(opened, closed=False, gap=True)
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
    assert "loop_fuse" in tick["supersede_pending"]["description"]
    assert "redirect_reason=pending_redirect_loop" in tick["supersede_pending"]["description"]
    assert "error=pending_redirect_loop" not in tick["supersede_pending"]["description"]
    assert "next_action=pending_redirect_loop" not in tick["supersede_pending"]["description"]
    assert "preserve_pending" in tick["supersede_pending"]["description"]
    assert "abandon_run" in tick["supersede_pending"]["description"]
    assert "gate_soft_continue=true" in tick["supersede_pending"]["description"]
    assert "never writes gate_soft_continue=false" in tick["supersede_pending"]["description"]
    assert "session_not_failed" in tick["supersede_pending"]["description"]
    assert tick["supersede_pending"]["default"] is False
    assert tools["swarm_doctor"]["annotations"]["readOnlyHint"] is True
    assert json.dumps(tools["swarm_tick"]["description"]).count("\\n        ") == 0
