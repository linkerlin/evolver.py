"""MCP server unit & in-process surface tests (算子即基因 P1-1)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evolver import __version__
from evolver.mcp_server import (
    ACTIVE_ONLY_TOOLS,
    IDLE_ONLY_TOOLS,
    asset_get,
    asset_search,
    build_server,
    cycle_timeline,
    episode_get,
    mailbox_ack,
    mailbox_poll,
    mailbox_send,
    rebuild_views,
    visible_tools_for_state,
)
from tests.mcp_surface import (
    MCP_ACTIVE_TOOL_NAMES,
    MCP_ALL_TOOL_NAMES,
    MCP_IDLE_TOOL_NAMES,
    MCP_PROMPT_NAMES,
    MCP_RESOURCE_URIS,
)


@pytest.fixture
def seeded_store(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.gep.asset_store import append_capsule, upsert_gene

    gene = {
        "type": "Gene",
        "id": "gene_fix_import",
        "name": "Fix missing import",
        "description": "Repair ImportError by adding the missing module import",
        "category": "repair",
    }
    capsule = {
        "type": "Capsule",
        "id": "cap_1",
        "gene_id": "gene_fix_import",
        "name": "capsule one",
        "description": "first capsule",
        "category": "repair",
    }
    gene_rich = {
        "type": "Gene",
        "id": "gene_applied_cooldown",
        "category": "optimize",
        "summary": "Selector penalizes recently-solidified genes so rounds stop re-dispatching",
        "signals_match": ["hub_offline", "selection_inefficiency"],
    }
    upsert_gene(gene)
    append_capsule(capsule)
    upsert_gene(gene_rich)


class TestAssetTools:
    def test_search_matches_name_and_description(self, seeded_store: None) -> None:
        hits = asset_search("import")
        ids = {h["id"] for h in hits}
        assert "gene_fix_import" in ids

    def test_search_no_match(self, seeded_store: None) -> None:
        assert asset_search("zzz_nonexistent") == []

    def test_search_multi_word_is_token_and(self, seeded_store: None) -> None:
        hits = asset_search("fix import")
        assert "gene_fix_import" in {h["id"] for h in hits}
        assert asset_search("fix zzz_nonexistent") == []

    def test_search_covers_summary_and_signals(self, seeded_store: None) -> None:
        by_summary = asset_search("selector penalizes")
        assert "gene_applied_cooldown" in {h["id"] for h in by_summary}
        by_signal = asset_search("hub_offline")
        assert "gene_applied_cooldown" in {h["id"] for h in by_signal}

    def test_search_empty_query(self, seeded_store: None) -> None:
        assert asset_search("   ") == []

    def test_get_round_trip(self, seeded_store: None) -> None:
        hit = asset_get("cap_1")
        assert hit["type"] == "Capsule"
        assert hit["gene_id"] == "gene_fix_import"

    def test_get_missing_raises(self, seeded_store: None) -> None:
        with pytest.raises(LookupError):
            asset_get("missing_id")


class TestMailboxTools:
    def test_send_visible_as_pending_outbound(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        sent = mailbox_send("task_request", {"task": "do-thing"}, priority="high")
        assert sent["status"] in ("pending", "queued", "new")
        polled = mailbox_poll(direction="outbound")
        assert any(m["id"] == sent["message_id"] for m in polled)

    def test_inbound_poll_ack_loop(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        from evolver.proxy.mailbox.store import MailboxStore

        store = MailboxStore(temp_workspace / ".evolver" / "proxy-mailbox")
        msg_id = store.write_inbound(id="m1", type="notice", payload={"hi": 1})

        polled = mailbox_poll()
        assert [m["id"] for m in polled] == [msg_id]
        assert mailbox_ack([msg_id]) == 1
        assert mailbox_poll() == []

    def test_invalid_direction_rejected(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        with pytest.raises(ValueError):
            mailbox_poll(direction="sideways")

    def test_invalid_priority_rejected(self, temp_workspace: Path) -> None:
        with pytest.raises(ValueError):
            mailbox_send("x", {}, priority="urgent")


class TestProjectionTools:
    def test_cycle_timeline_and_rebuild(self, temp_workspace: Path) -> None:
        from evolver.gep.asset_store import append_event_jsonl

        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "evt_1",
                "run_id": "r1",
                "timestamp": "2026-08-24T00:00:00Z",
                "outcome": {"status": "success", "score": 1.0},
            }
        )
        summary = rebuild_views()
        assert summary["event_count"] == 1
        assert summary["cycles"] == 1

        timeline = cycle_timeline(limit=5)
        assert timeline[0]["stage"] == "solidified"


class TestFsmServerSurface:
    def test_visible_tools_partition_idle_vs_active(self) -> None:
        all_names = sorted(MCP_ALL_TOOL_NAMES)
        assert set(visible_tools_for_state("IDLE", all_names)) == MCP_IDLE_TOOL_NAMES
        assert set(visible_tools_for_state("ACTIVE_RUN", all_names)) == MCP_ACTIVE_TOOL_NAMES
        assert IDLE_ONLY_TOOLS.isdisjoint(ACTIVE_ONLY_TOOLS)

    def test_build_server_switches_catalog_by_pending_state(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.solidify import write_state_for_solidify

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        monkeypatch.setenv("EVOLUTION_DIR", str(temp_workspace / "evolution"))

        server = build_server()
        idle_tools = asyncio.run(server.list_tools())
        assert {t.name for t in idle_tools} == MCP_IDLE_TOOL_NAMES

        write_state_for_solidify({"run_id": "run_active_1", "signals": []})
        active_tools = asyncio.run(server.list_tools())
        assert {t.name for t in active_tools} == MCP_ACTIVE_TOOL_NAMES

        prompts = asyncio.run(server.list_prompts())
        assert {p.name for p in prompts} == MCP_PROMPT_NAMES
        resources = asyncio.run(server.list_resources())
        assert {str(r.uri) for r in resources} == MCP_RESOURCE_URIS

    def test_episode_get_returns_a_recorded_round(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(temp_workspace / "evolution"))
        from evolver.gep import episode_record

        body = episode_record.build_episode(
            {
                "event": {
                    "type": "EvolutionEvent",
                    "id": "evt_mcp_1",
                    "run_id": "run_mcp",
                    "timestamp": "2026-10-02T00:00:00.000Z",
                    "gene_id": "gene_a",
                    "mutation": {"id": "mut_1", "category": "repair"},
                    "diff_snapshot": "+x",
                    "outcome": {"status": "success", "score": 1.0},
                },
                "validation_result": {"ok": True, "results": []},
                "fitness_verdict": None,
                "gate": {"accepted": True},
            }
        )
        stored = episode_record.record_episode(body)
        assert episode_get(stored["id"]) == body

    def test_episode_get_missing_id_raises(self) -> None:
        with pytest.raises(LookupError):
            episode_get("sha256:nope")

    def test_evolver_swarm_prompt_and_resources_readable(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        server = build_server()

        result = asyncio.run(server.get_prompt("evolver_swarm"))
        text = result.messages[0].content.text
        assert "EVOLVER SWARM" in text
        assert "evolve_begin" in text
        assert "evolve_settle" in text

        contents = asyncio.run(server.read_resource("evolver://status"))
        data = json.loads(next(iter(contents)).content)
        assert data["ok"] is True
        assert data["version"] == __version__
        assert data["fsm_state"] == "IDLE"

    def test_default_instructions_concise_and_hijack_invariant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plain = build_server().instructions or ""
        assert "EVOLVER SWARM" in plain
        assert "evolve_begin" in plain
        assert "run_lens" in plain
        assert "evolve_settle" in plain
        assert len(plain) < 900
        monkeypatch.setattr("evolver.config.SWARM_AUTO_HIJACK", True)
        assert (build_server().instructions or "") == plain
