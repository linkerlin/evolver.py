"""Swarm evolution — 3-tool FSM host orchestration + internal engine seams (v1.114.0).

Covers evolver.swarm:
- Concise 3-tool FSM takeover prompt (`build_instrument_prompt`)
- Core FSM orchestrators (`evolve_begin`, `evolve_run_lens`, `evolve_settle`, `evolve_status`)
- Cycle-boundary blackbox & immutable `episode_record` settlement
- Internal CLI/engine seams (`swarm_distill`, `swarm_hypothesis`, `swarm_propose`,
  `swarm_solidify`, `swarm_supervise`, `swarm_hooks`, `swarm_hook_event`,
  `swarm_report`, `swarm_feedback`, HITL, mutual exclusion, staleness guards)
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from evolver import __version__
from evolver.swarm import (
    SWARM_PROTOCOL_VERSION,
    build_instrument_prompt,
    evolve_begin,
    evolve_run_lens,
    evolve_settle,
    evolve_status,
    fsm_state,
    swarm_distill,
    swarm_feedback,
    swarm_hook_event,
    swarm_hooks,
    swarm_hypothesis,
    swarm_propose,
    swarm_report,
    swarm_solidify,
    swarm_status,
    swarm_supervise,
)
from tests.conftest import SYNTHETIC_TRAIN_ID, synth_hypothesis


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point all evolver state into tmp_path."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    yield tmp_path


def _solidify_scene(run_id: str, event_id: str) -> dict[str, Any]:
    """Minimal settlement scene for the episode-record branch of solidify."""
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": event_id,
            "run_id": run_id,
            "timestamp": "2026-10-02T00:00:00.000Z",
            "gene_id": "gene_a",
            "mutation": {"id": "mut_1", "category": "repair"},
            "diff_snapshot": "--- a.py\n+++ b.py\n-x = 1\n+x = 2\n",
            "outcome": {"status": "success", "score": 1.0},
            "blast_radius": {"files": 1, "lines": 2},
        },
        "validation_result": {"ok": True, "results": []},
        "fitness_verdict": None,
        "gate": {"accepted": True, "reason": "improved"},
    }


class TestInstrumentPrompt:
    def test_contains_fsm_protocol_sections(self) -> None:
        prompt = build_instrument_prompt(
            {"agent_name": "zcode-1", "workspace_root": "/ws", "fsm_state": "IDLE"}
        )
        for needle in (
            "EVOLVER SWARM",
            "零干预三工具原子协议",
            f"(v{SWARM_PROTOCOL_VERSION})",
            "zcode-1",
            "evolve_begin",
            "run_lens",
            "evolve_settle",
            "draft_preserved",
            "actionable_fix",
            "import_impact",
            "ast_hotspot",
            "trace_locator",
        ):
            assert needle in prompt, f"missing section: {needle}"
        # Legacy 6-step manual tools must not clutter the new takeover prompt
        assert "swarm_tick" not in prompt
        assert "swarm_boot" not in prompt

    def test_fsm_opening_action_branches(self) -> None:
        idle = build_instrument_prompt(
            {"agent_name": "a", "workspace_root": "/ws", "fsm_state": "IDLE"}
        )
        assert "FSM = `IDLE`，下一步：`evolve_begin`" in idle

        active = build_instrument_prompt(
            {
                "agent_name": "a",
                "workspace_root": "/ws",
                "pending_solidify": True,
                "fsm_state": "ACTIVE_RUN",
            }
        )
        assert "FSM = `ACTIVE_RUN`，下一步：`evolve_settle`" in active

        paused = build_instrument_prompt(
            {
                "agent_name": "a",
                "workspace_root": "/ws",
                "fsm_state": "IDLE",
                "supervision": {"state": "paused"},
            }
        )
        assert "下一步：`await_supervisor_resume`" in paused

        # Active unsettled run takes priority over pause so the round can settle cleanly
        active_paused = build_instrument_prompt(
            {
                "agent_name": "a",
                "workspace_root": "/ws",
                "pending_solidify": True,
                "fsm_state": "ACTIVE_RUN",
                "supervision": {"state": "paused"},
            }
        )
        assert "下一步：`evolve_settle`" in active_paused

    def test_working_session_preview_rendered(self) -> None:
        prompt = build_instrument_prompt(
            {
                "agent_name": "a",
                "workspace_root": "/ws",
                "fsm_state": "IDLE",
                "working_session": {"preview": "ruled out off-by-one in parser"},
            }
        )
        assert "WORKING_SESSION.md" in prompt
        assert "ruled out off-by-one in parser" in prompt


class TestFsmCoreTools:
    def test_status_shapes(self, isolated_swarm_env: Path) -> None:
        mcp_st = evolve_status()
        assert mcp_st["ok"] is True
        assert mcp_st["version"] == __version__
        assert mcp_st["protocol_version"] == SWARM_PROTOCOL_VERSION
        assert mcp_st["fsm_state"] == "IDLE"
        assert mcp_st["allowed_tools"] == ["evolve_begin", "evolve_status"]
        assert mcp_st["next_action"] == "evolve_begin"
        assert set(mcp_st["available_lenses"]) >= {
            "ast_hotspot",
            "contract_surface",
            "import_impact",
            "trace_locator",
        }

        eng_st = swarm_status()
        assert eng_st["ok"] is True
        assert eng_st["protocol_version"] == SWARM_PROTOCOL_VERSION
        assert eng_st["workspace_root"] == str(isolated_swarm_env)
        assert eng_st["genes"] >= 1
        assert eng_st["pending_solidify"] is False
        assert eng_st["bench_pack_gate"]["armed"] is False

    @pytest.mark.asyncio
    async def test_evolve_begin_discovery_preview_and_empty_rejection(
        self, isolated_swarm_env: Path
    ) -> None:
        swarm_hook_event(
            "signal_detect",
            payload={"content": "ImportError: cannot import name 'foo'"},
        )
        preview = await evolve_begin(hypothesis="", auto_discover=True)
        assert preview["ok"] is True
        assert preview["discovery_only"] is True
        assert preview["fsm_state"] == "IDLE"
        assert preview["next_action"] == "evolve_begin"
        assert "hypothesis_template" in preview
        assert isinstance(preview["recommended_operators"], list)
        assert fsm_state() == "IDLE"

        empty = await evolve_begin(hypothesis="   ", auto_discover=False)
        assert empty["ok"] is False
        assert empty["error"] == "empty_hypothesis"
        assert empty["fsm_state"] == "IDLE"
        assert fsm_state() == "IDLE"

    @pytest.mark.asyncio
    async def test_evolve_begin_locks_hypothesis_captures_stdout_and_blocks_reentry(
        self, isolated_swarm_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from evolver.gep import hypothesis as hypothesis_mod

        res = await evolve_begin(
            hypothesis="Fix parser off-by-one when token stream ends on newline",
            target_files=["src/parser.py"],
            agent_name="tester",
        )
        assert capsys.readouterr().out == ""
        assert res["ok"] is True
        assert res["fsm_state"] == "ACTIVE_RUN"
        assert res["run_id"]
        assert res["next_action"] == "evolve_settle"
        assert res["blackbox_started_at"]

        stored = hypothesis_mod.load_hypothesis()
        assert stored is not None
        assert stored["run_id"] == res["run_id"]
        assert stored["target_hook"] == "src/parser.py"

        # Calling evolve_begin again while ACTIVE_RUN is refused cleanly
        again = await evolve_begin(hypothesis="Another claim")
        assert again["ok"] is False
        assert again["error"] == "fsm_state_mismatch"
        assert again["fsm_state"] == "ACTIVE_RUN"
        assert again["next_action"] == "evolve_settle"

    @pytest.mark.asyncio
    async def test_evolve_begin_val_seal_breach_refused(
        self, temp_workspace: Path, armed_pack: dict[str, Any]
    ) -> None:
        _ = (temp_workspace, armed_pack)
        res = await evolve_begin(hypothesis="Tailor fix specifically for fixture val task 1")
        assert res["ok"] is False
        assert res["error"] == "val_seal_breach"
        assert res["fsm_state"] == "IDLE"
        assert fsm_state() == "IDLE"

    @pytest.mark.asyncio
    async def test_run_lens_logs_into_active_blackbox(self, isolated_swarm_env: Path) -> None:
        (isolated_swarm_env / "demo.py").write_text(
            "def f():\n    try:\n        return 1\n    except Exception:\n        pass\n",
            encoding="utf-8",
        )
        begun = await evolve_begin(hypothesis="Remove silent exception swallow in demo.py")
        assert begun["ok"] is True

        lens_res = evolve_run_lens(name="ast_hotspot", target="demo.py")
        assert lens_res["ok"] is True
        assert lens_res["read_only"] is True
        assert lens_res["fsm_state"] == "ACTIVE_RUN"

        st = evolve_status()
        assert st["active_blackbox"] is not None
        assert st["active_blackbox"]["lens_calls_count"] == 1

    def test_evolve_settle_refuses_when_idle(self, isolated_swarm_env: Path) -> None:
        res = evolve_settle(summary="nothing active")
        assert res["ok"] is False
        assert res["error"] == "fsm_state_mismatch"
        assert res["fsm_state"] == "IDLE"
        assert res["next_action"] == "evolve_begin"

    def test_evolve_settle_orphan_cli_run_preserves_draft_and_returns_idle(
        self, isolated_swarm_env: Path
    ) -> None:
        import subprocess

        from evolver.gep.solidify import write_state_for_solidify

        subprocess.run(["git", "init", "-q"], cwd=isolated_swarm_env, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.local"], cwd=isolated_swarm_env, check=True
        )
        subprocess.run(["git", "config", "user.name", "T"], cwd=isolated_swarm_env, check=True)
        target = isolated_swarm_env / "demo.py"
        target.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=isolated_swarm_env, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
            cwd=isolated_swarm_env,
            check=True,
        )
        # Edit tracked file without recording a hypothesis (simulates CLI `up --once`).
        target.write_text("def f() -> int:\n    return 42\n", encoding="utf-8")
        write_state_for_solidify(
            {
                "run_id": "run_cli_orphan",
                "selected_gene_id": "g_orphan",
                "mutation": {"id": "mut_orphan", "validation": []},
            }
        )
        assert fsm_state() == "ACTIVE_RUN"

        settled = evolve_settle(summary="Settle orphan CLI run")
        assert settled["ok"] is False
        assert settled["error"] == "hypothesis_missing"
        assert settled["outcome"] == "draft_preserved"
        assert settled["fsm_state"] == "IDLE"
        assert fsm_state() == "IDLE"
        assert "return 42" in target.read_text(encoding="utf-8")
        blob = json.dumps(settled, ensure_ascii=False)
        for legacy in ("swarm_hypothesis", "swarm_propose", "swarm_solidify", "swarm_tick"):
            assert legacy not in blob

    def test_evolve_settle_can_bind_hypothesis_or_abandon_orphan_run(
        self, isolated_swarm_env: Path
    ) -> None:
        import subprocess

        from evolver.gep.solidify import write_state_for_solidify

        subprocess.run(["git", "init", "-q"], cwd=isolated_swarm_env, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.local"], cwd=isolated_swarm_env, check=True
        )
        subprocess.run(["git", "config", "user.name", "T"], cwd=isolated_swarm_env, check=True)
        target = isolated_swarm_env / "demo.py"
        target.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=isolated_swarm_env, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
            cwd=isolated_swarm_env,
            check=True,
        )

        # 1. Passing hypothesis=... settles the unhypothesized run directly
        write_state_for_solidify(
            {
                "run_id": "run_bind_hyp",
                "selected_gene_id": "g_bind",
                "mutation": {"id": "mut_bind", "validation": []},
            }
        )
        bound = evolve_settle(
            summary="Bound hypothesis at settle",
            hypothesis="Keep demo.f deterministic and return 1",
        )
        assert bound["ok"] is True
        assert bound["fsm_state"] == "IDLE"

        # 2. Passing abandon=True closes ACTIVE_RUN preserving edits without validating
        target.write_text("def f() -> int:\n    return 99\n", encoding="utf-8")
        write_state_for_solidify(
            {
                "run_id": "run_abandon_me",
                "selected_gene_id": "g_ab",
                "mutation": {"id": "mut_ab", "validation": []},
            }
        )
        ab = evolve_settle(abandon=True)
        assert ab["ok"] is True
        assert ab["status"] == "abandoned"
        assert ab["outcome"] == "draft_preserved"
        assert ab["fsm_state"] == "IDLE"
        assert "return 99" in target.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_evolve_begin_force_takeover_and_corrupt_state_reset(
        self, isolated_swarm_env: Path
    ) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.gep.solidify import write_state_for_solidify

        write_state_for_solidify(
            {
                "run_id": "run_wedged",
                "selected_gene_id": "g_wedged",
                "mutation": {"id": "mut_wedged", "validation": []},
            }
        )
        assert fsm_state() == "ACTIVE_RUN"

        taken = await evolve_begin(
            hypothesis="Force takeover of wedged run with explicit claim",
            force_takeover=True,
            auto_discover=False,
        )
        assert taken["ok"] is True
        assert taken["taken_over"] is True
        assert taken["fsm_state"] == "ACTIVE_RUN"
        assert taken["run_id"] != "run_wedged"

        # Corrupt solidify state fails safe to ACTIVE_RUN, then self-heals on settle
        state_path = get_solidify_state_path()
        state_path.write_text("{corrupt json", encoding="utf-8")
        assert fsm_state() == "ACTIVE_RUN"

        reset_res = evolve_settle()
        assert reset_res["ok"] is False
        assert reset_res["error"] == "corrupt_run_state_reset"
        assert reset_res["fsm_state"] == "IDLE"
        assert fsm_state() == "IDLE"


class TestSwarmHypothesis:
    """演进方案 §5.3 — internal hypothesis recorder supports plain string or §5.3 dict."""

    def test_valid_dict_lands_on_disk(self, temp_workspace: Path) -> None:
        from evolver.gep import hypothesis as hypothesis_mod

        result = swarm_hypothesis(synth_hypothesis())
        assert result["ok"] is True
        assert result["next_action"] == "evolve_settle"
        stored = hypothesis_mod.load_hypothesis()
        assert stored is not None
        assert stored["dimension"] == "content"
        assert [ref["id"] for ref in stored["mechanism_check"]] == [SYNTHETIC_TRAIN_ID]
        assert Path(result["hypothesis_path"]) == hypothesis_mod.hypothesis_path()

    def test_plain_sentence_synthesizes_valid_record(self, temp_workspace: Path) -> None:
        from evolver.gep import hypothesis as hypothesis_mod

        result = swarm_hypothesis("Fix CLI parser timeout handling")
        assert result["ok"] is True
        stored = hypothesis_mod.load_hypothesis()
        assert stored is not None
        assert stored["dimension"] == "tool"
        assert stored["hypothesis"] == "Fix CLI parser timeout handling"

    def test_bad_dimension_soft_rejected(self, temp_workspace: Path) -> None:
        result = swarm_hypothesis(synth_hypothesis(dimension="vibes"))
        assert result["ok"] is False
        assert result["error"] == "hypothesis_rejected"
        assert result["failure_mode"]["mode"] == "soft"
        assert result["failure_mode"]["retryable"] is True
        assert result["next_action"] == "evolve_begin"

    def test_empty_or_invalid_type_rejected(self, temp_workspace: Path) -> None:
        from evolver.gep import hypothesis as hypothesis_mod

        empty_res = swarm_hypothesis("   ")
        assert empty_res["ok"] is False
        assert empty_res["error"] == "hypothesis_rejected"

        bad_type = swarm_hypothesis(12345)  # type: ignore[arg-type]
        assert bad_type["ok"] is False
        assert bad_type["error"] == "hypothesis_rejected"
        assert hypothesis_mod.load_hypothesis() is None

    def test_mechanism_check_citing_val_is_refused_by_gate(
        self, temp_workspace: Path, armed_pack: dict[str, Any]
    ) -> None:
        from evolver.gep import hypothesis as hypothesis_mod

        _ = armed_pack
        result = swarm_hypothesis(
            synth_hypothesis(mechanism_check=[{"id": "fixture-val-1", "before": 0.0, "after": 1.0}])
        )
        assert result["ok"] is True
        ok, reason, detail = hypothesis_mod.validate_for_gate(hypothesis_mod.load_hypothesis())
        assert ok is False
        assert reason == hypothesis_mod.REASON_VAL_REF
        assert detail["val_refs"] == ["fixture-val-1"]
        with pytest.raises(hypothesis_mod.HypothesisError, match="fixture-val-1"):
            hypothesis_mod.require_for_gate(hypothesis_mod.load_hypothesis())


class TestDistillSolidifyReport:
    def test_distill_installs_gene(self, isolated_swarm_env: Path) -> None:
        response = (
            "Work done. Extracted asset:\n"
            "```json\n"
            '{"type": "Gene", "id": "gene_swarm_demo", "category": "repair", '
            '"summary": "demo gene distilled from host work", '
            '"signals_match": ["ImportError"]}\n'
            "```\n"
        )
        result = swarm_distill(response)
        assert result["ok"] is True
        assert result["genes"] == 1
        assert result["errors"] == []
        assert result["next_action"] == "evolve_settle"

        from evolver.gep.asset_store import load_genes

        assert any(g.get("id") == "gene_swarm_demo" for g in load_genes())

    def test_distill_empty_rejected(self, isolated_swarm_env: Path) -> None:
        result = swarm_distill("   ")
        assert result["ok"] is False
        assert result["error"] == "empty_response"

    def test_distill_zero_assets_returns_format_hint(self, isolated_swarm_env: Path) -> None:
        result = swarm_distill("Fixed the retry logic, all tests pass.")
        assert result["genes"] == 0
        assert "```json" in result["hint"]
        assert "innovate" in result["hint"]

    def test_distill_valid_gene_has_no_hint(self, isolated_swarm_env: Path) -> None:
        response = (
            "```json\n"
            '{"type": "Gene", "id": "gene_hint_ok", "category": "repair", '
            '"summary": "x", "signals_match": ["ImportError"]}\n'
            "```\n"
        )
        result = swarm_distill(response)
        assert result["genes"] == 1
        assert "hint" not in result
        assert result["next_action"] == "evolve_settle"

    def test_distill_stores_the_host_account_as_a_clue(self, isolated_swarm_env: Path) -> None:
        response = (
            "I searched the logs and found the retry loop.\n\n"
            "```json\n"
            '{"type": "Gene", "id": "gene_clue_demo", "category": "repair", '
            '"summary": "x", "signals_match": ["ImportError"]}\n'
            "```\n"
        )
        result = swarm_distill(response)
        assert result["ok"] is True
        assert result["clue"]["ok"] is True
        assert result["clue"]["source"] == "host_distill"

        from evolver.gep import episode_clue

        clues = episode_clue.recent_clues()
        assert any("retry loop" in c["text"] for c in clues)

    def test_distill_dry_run_stores_no_clue(self, isolated_swarm_env: Path) -> None:
        result = swarm_distill("I searched the logs and found the retry loop.", dry_run=True)
        assert result["ok"] is True
        assert "clue" not in result
        from evolver.gep import episode_clue

        assert episode_clue.recent_clues() == []

    def test_distill_malformed_block_never_crashes(self, isolated_swarm_env: Path) -> None:
        response = (
            "```json\nnot json at all\n```\n"
            "```json\n"
            '{"type": "Gene", "id": "gene_ok", "category": "repair", '
            '"summary": "x", "signals_match": ["hub"]}\n'
            "```\n"
        )
        result = swarm_distill(response)
        assert result["ok"] is True
        assert result["genes"] == 1


class TestTickPreservesPhaseTimings:
    def test_record_tick_preserves_phase_timings(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.paths import get_evolution_dir
        from evolver.swarm import _record_tick

        evo = get_evolution_dir()
        evo.mkdir(parents=True, exist_ok=True)
        state_path = evo / "swarm_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "ticks": 41,
                    "last_tick_phase_timings": {"collect": 0.02, "hub": 0.1},
                    "last_tick_total_s": 0.12,
                }
            ),
            encoding="utf-8",
        )
        _record_tick({"run_id": "r", "cycle_id": "c", "next_action": "evolve_settle"})
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["ticks"] == 42
        assert data["last_tick_phase_timings"] == {"collect": 0.02, "hub": 0.1}
        assert data["last_tick_total_s"] == 0.12

    def test_distill_records_landed_gene_ids(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.gep.solidify import write_state_for_solidify

        write_state_for_solidify({"run_id": "run_x", "selected_gene_id": "gene_playbook"})
        response = (
            "```json\n"
            '{"type": "Gene", "id": "gene_landed_x", "category": "repair", '
            '"summary": "x", "signals_match": ["ImportError"]}\n'
            "```\n"
        )
        assert swarm_distill(response)["genes"] == 1
        state = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        assert state["last_run"]["landed_gene_ids"] == ["gene_landed_x"]

    def test_distill_bad_category_hint_plus_errors(self, isolated_swarm_env: Path) -> None:
        response = (
            "```json\n"
            '{"type": "Gene", "id": "gene_bad_cat", "category": "innovation", '
            '"summary": "x", "signals_match": ["ImportError"]}\n'
            "```\n"
        )
        result = swarm_distill(response)
        assert result["genes"] == 0
        assert result["hint"]
        assert result["errors"]

    def test_solidify_without_pending_run(self, isolated_swarm_env: Path) -> None:
        result = swarm_solidify()
        assert result["ok"] is False
        assert result["error"] == "no_pending_run"

    def test_solidify_failure_carries_failure_mode(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.solidify as solidify_mod

        monkeypatch.setattr(
            solidify_mod,
            "solidify",
            lambda **kw: {
                "ok": False,
                "error": "validation_failed",
                "details": {"validation_result": {"ok": False, "stage": "mypy"}},
            },
        )
        result = swarm_solidify()
        assert result["failure_mode"] == {
            "mode": "soft",
            "reasonClass": "validation",
            "retryable": True,
        }
        assert result["next_action"] == "evolve_begin"

    def test_solidify_hard_failure_directs_stop(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.solidify as solidify_mod

        monkeypatch.setattr(
            solidify_mod, "solidify", lambda **kw: {"ok": False, "error": "not_a_git_repo"}
        )
        result = swarm_solidify()
        assert result["failure_mode"]["retryable"] is False
        assert result["next_action"] == "stop_and_report"

    def test_solidify_success_records_the_settled_round(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.solidify as solidify_mod
        from evolver.gep.evidence import save_evidence

        save_evidence("run_ep_1", "evt_ep_1", _solidify_scene("run_ep_1", "evt_ep_1"))
        monkeypatch.setattr(
            solidify_mod, "solidify", lambda **kw: {"ok": True, "event_id": "evt_ep_1"}
        )
        result = swarm_solidify()
        assert result["ok"] is True
        assert result["episode"]["ok"] is True
        assert result["episode"]["round_key"] == "#evt_ep_1" or result["episode"][
            "round_key"
        ].endswith("#evt_ep_1")
        assert result["episode_id"] == result["episode"]["id"]

    def test_solidify_reject_records_the_settled_round(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.solidify as solidify_mod
        from evolver.gep.evidence import save_evidence

        scene = _solidify_scene("run_ep_rej", "evt_ep_rej")
        scene["event"]["outcome"] = {"status": "failed", "error": "bench_pack_rejected"}
        scene["gate"] = {"accepted": False, "reason": "flat"}
        save_evidence("run_ep_rej", "evt_ep_rej", scene)
        monkeypatch.setattr(
            solidify_mod,
            "solidify",
            lambda **kw: {"ok": False, "error": "bench_pack_rejected", "event_id": "evt_ep_rej"},
        )
        result = swarm_solidify()
        assert result["ok"] is False
        assert result["episode"]["ok"] is True
        assert result["episode_id"] == result["episode"]["id"]

    def test_solidify_success_without_a_scene_still_succeeds(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.solidify as solidify_mod

        monkeypatch.setattr(
            solidify_mod, "solidify", lambda **kw: {"ok": True, "event_id": "evt_missing"}
        )
        result = swarm_solidify()
        assert result["ok"] is True
        assert result["episode"] == {
            "ok": False,
            "error": "scene_missing",
            "event_id": "evt_missing",
        }

    def test_report_heartbeat(self, isolated_swarm_env: Path) -> None:
        result = swarm_report(category="friction", description="demo", resolution="none")
        assert result["ok"] is True
        assert isinstance(result["report"], dict)


class TestFeedbackChannel:
    def test_feedback_records_and_injects_repair_bias(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.asset_store import consume_pending_signals

        result = swarm_feedback(
            primary_score=0.2,
            textual_gradient="修复未生效，锚点仍然失配",
            agent_name="tester",
        )
        assert result["ok"] is True
        assert result["degraded"] is True

        pending = consume_pending_signals()
        assert "swarm_feedback:degraded" in pending
        assert any(s.startswith("swarm_feedback:gradient:") for s in pending)

        status = swarm_status()
        assert status["feedback"]["recent_count"] == 1
        assert status["feedback"]["last"]["primary_score"] == 0.2

    def test_feedback_ok_path_no_repair_bias(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.asset_store import consume_pending_signals

        result = swarm_feedback(primary_score=0.95, textual_gradient="顺利")
        assert result["degraded"] is False
        assert consume_pending_signals() == ["swarm_feedback:ok"]

    def test_feedback_invalid_score_rejected(self, isolated_swarm_env: Path) -> None:
        result = swarm_feedback(primary_score=5.0)
        assert result["ok"] is False
        assert "invalid_feedback" in result["error"]

    def test_status_reports_feedback_stability(self, isolated_swarm_env: Path) -> None:
        for _ in range(4):
            swarm_feedback(primary_score=0.8)
        stability = swarm_status()["feedback"]["stability"]
        assert stability is not None
        assert stability["n"] == 4
        assert stability["stddev"] == 0.0
        assert stability["converged"] is True


def _seed_pending_run(run_id: str = "run_hitl_test") -> None:
    from evolver.gep.solidify import write_state_for_solidify

    write_state_for_solidify(
        {"run_id": run_id, "selected_gene_id": "gene_test", "mutation": {"id": "m1"}}
    )


class TestHitlGate:
    def test_skip_without_pending_run_is_refused(self, isolated_swarm_env: Path) -> None:
        result = swarm_solidify(skip_validation=True, agent_name="tester")
        assert result["ok"] is False
        assert result["error"] == "skip_validation_requires_pending_run"

    def test_mode_off_auto_approves_with_audit(self, isolated_swarm_env: Path) -> None:
        _seed_pending_run()
        result = swarm_solidify(skip_validation=True, agent_name="tester")
        assert result.get("error") == "hypothesis_missing"
        journal = isolated_swarm_env / "evolution" / "hitl_approvals.jsonl"
        assert journal.exists() and "auto_approved" in journal.read_text(encoding="utf-8")

    def test_mode_on_blocks_until_approved(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.HITL_MODE", "on")
        _seed_pending_run("run_on")
        blocked = swarm_solidify(skip_validation=True, agent_name="tester")
        assert blocked["ok"] is False
        assert blocked["error"] == "hitl_pending"
        assert blocked["next_action"] == "await_human_approval"

        from evolver.gep.hitl import resolve_approval

        request_id = blocked["approval"]["request_id"]
        assert resolve_approval(request_id, approve=True, decided_by="human")["ok"]

        passed = swarm_solidify(skip_validation=True, agent_name="tester")
        assert passed.get("error") == "hypothesis_missing"

    def test_mode_on_rejected_blocks(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.HITL_MODE", "on")
        _seed_pending_run("run_rej")
        blocked = swarm_solidify(skip_validation=True)
        from evolver.gep.hitl import resolve_approval

        resolve_approval(blocked["approval"]["request_id"], approve=False)
        again = swarm_solidify(skip_validation=True)
        assert again["error"] == "hitl_rejected"
        assert again["next_action"] == "evolve_begin"

    def test_status_exposes_hitl_state(self, isolated_swarm_env: Path) -> None:
        status = swarm_status()
        assert status["hitl"]["mode"] in ("on", "off")
        assert isinstance(status["hitl"]["pending"], int)


class TestSupervision:
    @pytest.mark.asyncio
    async def test_paused_begin_refuses_cycle(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.supervision import set_state

        set_state(True, by="human", reason="hold on")
        result = await evolve_begin(hypothesis="Attempt while paused", agent_name="tester")
        assert result["ok"] is False
        assert result["paused"] is True
        assert result["error"] == "supervision_paused"
        assert result["next_action"] == "await_supervisor_resume"
        assert result.get("run_id") is None

    @pytest.mark.asyncio
    async def test_resume_allows_begin_again(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.supervision import set_state

        set_state(True, by="human")
        set_state(False, by="human")
        result = await evolve_begin(hypothesis="Resume works")
        assert result["ok"] is True
        assert result["run_id"]

    def test_solidify_veto_blocks(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.supervision import add_veto

        add_veto("solidify:", by="human", note="freeze mutations")
        result = swarm_solidify()
        assert result["ok"] is False
        assert result["error"] == "supervision_veto"
        assert result["next_action"] == "evolve_begin"

    def test_supervise_wrapper_roundtrip(self, isolated_swarm_env: Path) -> None:
        assert swarm_supervise("status")["supervision"]["state"] == "running"
        paused = swarm_supervise("pause", reason="check")
        assert paused["state"] == "paused"
        directive = swarm_supervise("direct", text="优先修复 flaky 测试")
        assert directive["ok"] is True
        veto = swarm_supervise("veto", pattern="gene_bad")
        assert veto["ok"] is True
        unveto = swarm_supervise("unveto", veto_id=veto["veto_id"])
        assert unveto["ok"] is True
        resumed = swarm_supervise("resume")
        assert resumed["state"] == "running"
        assert swarm_supervise("sideways")["ok"] is False  # type: ignore[arg-type]

    def test_status_exposes_supervision(self, isolated_swarm_env: Path) -> None:
        status = swarm_status()
        assert status["supervision"]["state"] == "running"
        assert "directives" in status["supervision"]


class TestHooksSurface:
    def test_hook_event_detects_and_injects_signals(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.asset_store import consume_pending_signals

        result = swarm_hook_event(
            "signal_detect",
            payload={"content": "request timeout after 30s and retry exhausted"},
        )
        assert result["ok"] is True
        assert "perf_bottleneck" in result["detected_signals"]
        assert "perf_bottleneck" in consume_pending_signals()

        journal = isolated_swarm_env / "evolution" / "hook_events.jsonl"
        assert journal.exists() and "signal_detect" in journal.read_text(encoding="utf-8")

    def test_hook_journal_lines_are_closed_json(self, isolated_swarm_env: Path) -> None:
        swarm_hook_event("session_start", payload={"content": "hello world"})
        swarm_hook_event("session_end", payload={"content": "bye world"})
        journal = isolated_swarm_env / "evolution" / "hook_events.jsonl"
        lines = journal.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert entry["source"] == "host-agent" and "at" in entry

    def test_hook_event_session_start_without_signals(self, isolated_swarm_env: Path) -> None:
        result = swarm_hook_event("session_start", payload={"content": "hello world"})
        assert result["ok"] is True
        assert result["detected_signals"] == []
        assert "nothing injected" in result["note"]

    def test_hook_event_multilingual_error_detected(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.asset_store import consume_pending_signals

        result = swarm_hook_event("session_end", payload={"content": "部署失败：构建异常退出"})
        assert "log_error" in result["detected_signals"]
        assert "log_error" in consume_pending_signals()

    def test_hook_event_unknown_rejected(self, isolated_swarm_env: Path) -> None:
        result = swarm_hook_event("pre_tool_use")
        assert result["ok"] is False
        assert "unknown_event" in result["error"]

    def test_hooks_status_and_install_dry_run(self, isolated_swarm_env: Path) -> None:
        status = swarm_hooks("status", platform="generic", project_dir=str(isolated_swarm_env))
        assert status["ok"] is True
        assert status["requested_platform"] == "generic"
        assert isinstance(status["preview"], list)

        install = swarm_hooks(
            "install", platform="generic", project_dir=str(isolated_swarm_env), dry_run=True
        )
        assert install["ok"] is True

        assert swarm_hooks("reinstall")["ok"] is False  # type: ignore[arg-type]


class TestMutualExclusion:
    @staticmethod
    def _held_lock(monkeypatch: pytest.MonkeyPatch) -> None:
        import contextlib

        @contextlib.contextmanager
        def _held(**kwargs: object) -> Iterator[bool]:
            _ = kwargs
            yield False

        monkeypatch.setattr("evolver.gep.instance_lock.instance_lock_ctx", _held)

    @pytest.mark.asyncio
    async def test_begin_refuses_under_held_lock(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._held_lock(monkeypatch)
        result = await evolve_begin(hypothesis="Test lock guard")
        assert result["ok"] is False
        assert result["error"] == "instance_lock_held"
        assert result["next_action"] == "stop_and_report"

    def test_solidify_refuses_under_held_lock(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._held_lock(monkeypatch)
        result = swarm_solidify()
        assert result["ok"] is False
        assert result["error"] == "instance_lock_held"
        assert result["next_action"] == "stop_and_report"
        assert "event_id" not in result

    def test_propose_refuses_under_held_lock(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._held_lock(monkeypatch)
        target = isolated_swarm_env / "proposed.md"
        result = swarm_propose(
            {
                "action": "patch",
                "edits": [{"op": "append", "file": "proposed.md", "content": "x\n"}],
            }
        )
        assert result["ok"] is False
        assert result["error"] == "instance_lock_held"
        assert result["next_action"] == "stop_and_report"
        assert not target.exists()


class TestCodeStaleness:
    def test_status_reports_staleness_surface(self, isolated_swarm_env: Path) -> None:
        result = swarm_status()
        assert "source_revision" in result
        assert result["source_revision"] is None or isinstance(result["source_revision"], str)
        cs = result["code_staleness"]
        assert cs is not None
        assert set(cs) == {"stale", "process_started_at", "newest_src_mtime"}
        assert cs["stale"] is False

    def test_staleness_detects_newer_source(self, isolated_swarm_env: Path) -> None:
        import os

        import psutil

        from evolver.swarm import _code_staleness

        real_ct = psutil.Process.create_time

        def fake_ct(self: psutil.Process) -> float:
            if os.getpid() == self.pid:
                return 0.0
            return real_ct(self)

        original = psutil.Process.create_time
        psutil.Process.create_time = fake_ct  # type: ignore[method-assign]
        try:
            cs = _code_staleness()
        finally:
            psutil.Process.create_time = original  # type: ignore[method-assign]
        assert cs is not None and cs["stale"] is True


class TestPendingSolidifyTruth:
    def _write_state(self, path: Path, run_id: str, done_id: str | None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"last_run": {"run_id": run_id}}
        if done_id is not None:
            data["last_solidify"] = {"run_id": done_id, "outcome": "success"}
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_landed_run_is_not_pending(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.swarm import _pending_solidify_state

        self._write_state(get_solidify_state_path(), "run_a", "run_a")
        assert _pending_solidify_state() is False
        assert swarm_status()["pending_solidify"] is False
        assert fsm_state() == "IDLE"

    def test_newer_run_is_pending(self, isolated_swarm_env: Path) -> None:
        from evolver.gep.paths import get_solidify_state_path
        from evolver.swarm import _pending_solidify_state

        self._write_state(get_solidify_state_path(), "run_b", "run_a")
        assert _pending_solidify_state() is True
        assert fsm_state() == "ACTIVE_RUN"

    def test_missing_file_not_pending(self, isolated_swarm_env: Path) -> None:
        from evolver.swarm import _pending_solidify_state

        assert _pending_solidify_state() is False
        assert fsm_state() == "IDLE"


class TestStaleImportGuard:
    def test_helper_shape(self) -> None:
        from evolver.swarm import _stale_import_error

        err = ImportError("cannot import name 'X' from 'evolver.config'")
        result = _stale_import_error(err)
        assert result["ok"] is False
        assert result["error"] == "code_stale_process"
        assert result["next_action"] == "reconnect_host"
        assert "X" in result["reason"]

    def test_distill_deep_import_returns_stale_error(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evolver.gep.distill as distill_mod
        from evolver import swarm

        def boom(*args: object, **kwargs: object) -> dict[str, Any]:
            _ = (args, kwargs)
            raise ImportError("cannot import name 'NEW_THING' from 'evolver.config'")

        monkeypatch.setattr(distill_mod, "install_distilled", boom)
        result = swarm.swarm_distill("```json\n[]\n```")
        assert result["ok"] is False
        assert result["error"] == "code_stale_process"
        assert result["next_action"] == "reconnect_host"


@pytest.mark.asyncio
async def test_e2e_no_baseline_soft_path_begin_and_solidify(
    isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """no_baseline environment gap soft-accepts cleanly without blocking evolve_begin."""
    from evolver.bench.frozen_gate import enrich_soft_accept
    from evolver.gep.solidify import solidify
    from evolver.ops.open_box import SOFT_GAP_ERRORS

    repo = isolated_swarm_env
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("e2e soft\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.delenv("EVOLVER_NO_PARENT_GIT", raising=False)

    def bare() -> dict[str, object]:
        return {"armed": True, "baseline": None, "train_ids": ["train-a"]}

    monkeypatch.setattr("evolver.bench.frozen_gate.gate_snapshot", bare)

    begun = await evolve_begin(
        hypothesis="Update README note while baseline is not yet measured",
        agent_name="e2e-soft",
    )
    assert begun["ok"] is True
    assert begun["fsm_state"] == "ACTIVE_RUN"
    assert begun["next_action"] == "evolve_settle"
    assert begun.get("error") not in SOFT_GAP_ERRORS

    soft = enrich_soft_accept({"accept": False, "reason": "no_baseline"})
    assert soft["accept"] is True and soft.get("soft_accept") is True
    assert soft.get("next_steps")

    def soft_verdict(**_kwargs: object) -> dict[str, object]:
        return {
            "armed": True,
            "accept": False,
            "verdict": "reject",
            "reason": "no_baseline",
        }

    monkeypatch.setattr("evolver.bench.frozen_gate.gate_verdict", soft_verdict)
    result = solidify(skip_validation=True)
    assert result.get("ok") is True
    assert result.get("soft_accept") is True
    assert result.get("next_action") != "await_human"
    assert result.get("error") not in SOFT_GAP_ERRORS
