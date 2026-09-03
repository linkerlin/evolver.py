"""Sprint 24.7: MCP server — thin tool surface over existing modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.mcp_server import (
    asset_get,
    asset_search,
    build_server,
    cycle_timeline,
    mailbox_ack,
    mailbox_poll,
    mailbox_send,
    rebuild_views,
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
    upsert_gene(gene)
    append_capsule(capsule)


class TestAssetTools:
    def test_search_matches_name_and_description(self, seeded_store: None) -> None:
        hits = asset_search("import")
        ids = {h["id"] for h in hits}
        assert "gene_fix_import" in ids

    def test_search_no_match(self, seeded_store: None) -> None:
        assert asset_search("zzz_nonexistent") == []

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
        # Daemon side writes an inbound message; agent side polls + acks.
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


class TestServerBuild:
    def test_build_server_registers_tools(self) -> None:
        import asyncio

        server = build_server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        expected = {
            "tool_asset_search",
            "tool_asset_get",
            "tool_mailbox_send",
            "tool_mailbox_poll",
            "tool_mailbox_ack",
            "tool_rebuild_views",
            "tool_cycle_timeline",
        }
        assert expected <= names

    def test_build_server_registers_swarm_tools(self) -> None:
        import asyncio

        server = build_server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert {
            "swarm_boot",
            "swarm_tick",
            "swarm_distill",
            "swarm_solidify",
            "swarm_feedback",
            "swarm_report",
            "swarm_status",
            "swarm_approvals",
            "swarm_approval_resolve",
            "swarm_supervise",
            "swarm_hooks",
            "swarm_hook_event",
        } <= names

    def test_evolver_swarm_prompt_registered_and_rendered(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        server = build_server()

        prompts = asyncio.run(server.list_prompts())
        assert "evolver_swarm" in {p.name for p in prompts}

        result = asyncio.run(server.get_prompt("evolver_swarm"))
        text = result.messages[0].content.text
        assert "EVOLVER SWARM" in text
        assert "swarm_tick" in text
