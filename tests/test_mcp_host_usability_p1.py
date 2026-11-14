"""P1 MCP host usability: FSM tool naming, timeline settlement, honest report."""

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
    def test_schema_titles_follow_the_public_name_and_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.solidify import write_state_for_solidify
        from evolver.mcp_server import build_server

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))

        server = build_server()
        idle_tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        begin = idle_tools["evolve_begin"]
        assert _schema(begin).get("title") == "evolve_beginArguments"
        assert str(begin.title or "").startswith("Core FSM:")
        assert "hypothesis" in (_schema(begin).get("properties") or {})

        search = idle_tools["tool_asset_search"]
        assert _schema(search).get("title") == "tool_asset_searchArguments"
        assert "auxiliary" in str(search.title or "").lower()

        timeline = idle_tools["tool_cycle_timeline"]
        assert "read-only auxiliary" in str(timeline.title or "").lower()

        write_state_for_solidify({"run_id": "r_naming", "signals": []})
        active_tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        assert str(active_tools["run_lens"].title or "").startswith("Core FSM:")
        assert str(active_tools["evolve_settle"].title or "").startswith("Core FSM:")


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
