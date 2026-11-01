"""P1 MCP host usability: naming, timeline settlement, honest report, short tick.

These assertions describe the host-visible contract after soft-accept. They
fail while schema titles still say ``tool_swarm_*``, a later success can sit
on ``stage=failed``, ``swarm_report(no_write=True)`` still claims new rules,
and ``swarm_tick`` has no way to skip the gene-preview prompt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evolver.gep.cycle_state_machine import (
    STAGE_FAILED,
    STAGE_SOLIDIFIED,
    build_cycle_timeline,
)


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point swarm state at tmp_path so a tick cannot touch the real tree."""
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


_CORE_LOOP = frozenset(
    {
        "swarm_boot",
        "swarm_tick",
        "swarm_distill",
        "swarm_hypothesis",
        "swarm_propose",
        "swarm_solidify",
        "swarm_feedback",
        "swarm_report",
    }
)


def _schema(tool: Any) -> dict[str, Any]:
    raw = tool.input_schema
    if isinstance(raw, dict):
        return raw
    dumped = raw.model_dump()
    assert isinstance(dumped, dict)
    return dumped


def _tool_payload(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None) or []
    if not content:
        pytest.fail(f"tool returned an empty payload: {result!r}")
    payload = json.loads(content[0].text)
    assert isinstance(payload, dict)
    return payload


class TestToolNaming:
    def test_schema_titles_follow_the_public_name_and_role(self) -> None:
        from evolver.mcp_server import build_server

        tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}

        tick = tools["swarm_tick"]
        tick_props = _schema(tick).get("properties") or {}
        assert _schema(tick).get("title") == "swarm_tickArguments"
        assert "prompt_mode" in tick_props
        assert "checklist_only" in tick_props
        assert str(tick.title or "").startswith("Core loop:")
        assert "core loop" in (tick.description or "").lower()
        assert not str(_schema(tick).get("title") or "").startswith("tool_swarm_")
        assert "dry_run" in (_schema(tools["swarm_report"]).get("properties") or {})

        search = tools["tool_asset_search"]
        assert _schema(search).get("title") == "tool_asset_searchArguments"
        assert "auxiliary" in str(search.title or "").lower()
        assert "auxiliary" in (search.description or "").lower()

        timeline = tools["tool_cycle_timeline"]
        assert "read-only auxiliary" in str(timeline.title or "").lower()

        for name, tool in tools.items():
            title = str(_schema(tool).get("title") or "")
            assert not title.startswith("tool_swarm_"), name
            if name in _CORE_LOOP:
                assert str(tool.title or "").startswith("Core loop:"), name
            elif name.startswith("tool_"):
                assert "auxiliary" in str(tool.title or "").lower(), name
            # Registered names stay put: hosts already call them.
            assert name in tools

    def test_instrument_says_tool_star_is_not_the_loop(self) -> None:
        from evolver.swarm import build_instrument_prompt

        prompt = build_instrument_prompt({"agent_name": "a", "workspace_root": "/ws"})
        assert "tool_*" in prompt
        assert "swarm_*" in prompt
        assert "辅助" in prompt


class TestCycleTimelineSettlement:
    def test_later_success_replaces_soft_failed(self) -> None:
        events = [
            {
                "type": "EvolutionEvent",
                "run_id": "r1",
                "outcome": {"status": "soft_failed", "error": "validation_failed_soft"},
            },
            {
                "type": "EvolutionEvent",
                "run_id": "r1",
                "outcome": {"status": "success", "score": 1.0},
            },
        ]
        row = build_cycle_timeline(events)[0]
        assert row["stage"] == STAGE_SOLIDIFIED
        assert row["outcome_status"] == "success"
        assert row["outcome_matches_stage"] is True

    def test_string_cycle_end_success_does_not_leave_stage_failed(self) -> None:
        events = [
            {
                "type": "EvolutionEvent",
                "run_id": "r1",
                "outcome": {"status": "success"},
            },
            {"type": "cycle_end", "run_id": "r1", "outcome": "success"},
        ]
        row = build_cycle_timeline(events)[0]
        assert row["stage"] == STAGE_SOLIDIFIED
        assert row["outcome_status"] == "success"
        assert row["outcome_matches_stage"] is True
        assert row["stage"] != STAGE_FAILED

    def test_tool_documents_stage_versus_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.asset_store import append_event_jsonl
        from evolver.mcp_server import build_server

        monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "evt_soft",
                "run_id": "r_soft",
                "timestamp": "2026-11-01T00:00:00Z",
                "outcome": {"status": "soft_failed", "error": "validation_failed_soft"},
            }
        )
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "evt_ok",
                "run_id": "r_soft",
                "timestamp": "2026-11-01T00:00:01Z",
                "outcome": {"status": "success", "score": 1.0},
            }
        )
        server = build_server()
        described = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        assert "outcome_status" in (described["tool_cycle_timeline"].description or "")
        assert "solidified" in (described["tool_cycle_timeline"].description or "")

        payload = _tool_payload(asyncio.run(server.call_tool("tool_cycle_timeline", {"limit": 5})))
        assert payload["ok"] is True
        assert payload["items"][0]["stage"] == "solidified"
        assert payload["items"][0]["outcome_status"] == "success"
        assert payload["items"][0]["outcome_matches_stage"] is True
        assert "last terminal" in payload["semantics"]


class TestReportNoWrite:
    def test_no_write_persists_nothing_and_says_so(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_report

        gep = temp_workspace / ".evolver" / "gep"
        evolution = temp_workspace / "memory" / "evolution"
        rules = gep / "autopoiesis_rules.json"
        lessons = evolution / "LESSONS_LEARNED.md"
        report_file = evolution / "self_report.json"
        pending = gep / "pending_signals.json"

        dry = swarm_report(
            category="runtime",
            description="traceback should stay off disk",
            resolution="none",
            no_write=True,
        )
        assert dry["ok"] is True
        assert dry["wrote"] is False
        assert dry["written"] == []
        assert dry["no_write"] is True
        summary = dry["report"]["friction_summary"]
        assert summary["total"] == 1
        assert summary["auto_encoded"] == 0
        assert dry["report"]["evolution"]["new_rules_this_run"] == 0
        assert dry["report"]["wrote"] is False
        assert not rules.exists()
        assert not lessons.exists()
        assert not report_file.exists()
        assert not pending.exists()

        alias = swarm_report(
            category="runtime",
            description="dry_run is the same promise",
            dry_run=True,
        )
        assert alias["wrote"] is False
        assert alias["dry_run"] is True
        assert not rules.exists()

    def test_default_report_lists_what_it_wrote(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_report

        result = swarm_report(category="runtime", description="persist this", resolution="noted")
        assert result["ok"] is True
        assert result["wrote"] is True
        written = set(result["written"])
        assert "LESSONS_LEARNED.md" in written
        assert "self_report.json" in written
        assert "autopoiesis_rules.json" in written
        lessons = temp_workspace / "memory" / "evolution" / "LESSONS_LEARNED.md"
        assert lessons.is_file()
        assert result["report"]["friction_summary"]["auto_encoded"] == 1


class TestShortTick:
    async def test_checklist_only_omits_gene_preview(self, isolated_swarm_env: Path) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick(checklist_only=True)
        assert result["ok"] is True
        assert result["prompt_mode"] == "short"
        shown = result.get("dispatch_prompt") or ""
        assert "GENOME EVOLUTION PROTOCOL" not in shown
        assert "Host Execution Checklist" in shown
        assert result["gene_preview_omitted"] is True
        assert result["checklist"]["steps"]
        artifact = Path(str(result["dispatch_prompt_artifact"]))
        assert artifact.is_file()
        full = artifact.read_text(encoding="utf-8")
        assert "GENOME EVOLUTION PROTOCOL" in full
        assert len(shown) < len(full)
        assert result["dispatch_prompt_resource"] == "evolver://dispatch/last"

    async def test_prompt_mode_short_matches_checklist_only(self, isolated_swarm_env: Path) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick(prompt_mode="short")
        assert result["prompt_mode"] == "short"
        assert "GENOME EVOLUTION PROTOCOL" not in (result.get("dispatch_prompt") or "")
        assert result["gene_preview_omitted"] is True

    async def test_full_prompt_stays_the_default(self, isolated_swarm_env: Path) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick()
        assert result["prompt_mode"] == "full"
        assert "GENOME EVOLUTION PROTOCOL" in (result.get("dispatch_prompt") or "")
        assert "gene_preview_omitted" not in result

    async def test_unknown_prompt_mode_does_not_run(self, isolated_swarm_env: Path) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick(prompt_mode="tiny")
        assert result["ok"] is False
        assert result["error"] == "invalid_prompt_mode"
