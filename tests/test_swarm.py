"""Swarm evolution — instrument prompt + closed-loop tools (v1.98.0).

Covers evolver.swarm: takeover prompt rendering, boot/hello, tick with stdout
capture (stdio MCP owns stdout), distill/solidify/report wrappers, and swarm
state persistence. No Node.js equivalent — Python-native design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.swarm import (
    SWARM_PROTOCOL_VERSION,
    build_instrument_prompt,
    swarm_boot,
    swarm_distill,
    swarm_feedback,
    swarm_report,
    swarm_solidify,
    swarm_status,
    swarm_tick,
)


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state (incl. mailbox repo root) into tmp_path."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    # Fast connection-refused instead of real-network timeouts (hub + ATP).
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    # Deterministic preflight: ambient host load must not abort cycles here.
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    yield tmp_path


class TestInstrumentPrompt:
    def test_contains_protocol_sections(self) -> None:
        prompt = build_instrument_prompt({"agent_name": "zcode-1", "workspace_root": "/ws"})
        for needle in (
            "EVOLVER SWARM",
            "宿主接管协议",
            "zcode-1",
            "swarm_tick",
            "swarm_distill",
            "swarm_solidify",
            "swarm_feedback",
            "swarm_report",
            "终止条件",
            "安全边界",
            "HITL",
            f"instrument v{SWARM_PROTOCOL_VERSION}",
        ):
            assert needle in prompt, f"missing section: {needle}"

    def test_state_interpolated(self) -> None:
        prompt = build_instrument_prompt(
            {"agent_name": "a", "workspace_root": "/ws", "tick_count": 7, "genes": 3}
        )
        assert "tick_count: 7" in prompt
        assert "genes: 3" in prompt


class TestBootAndStatus:
    def test_boot_returns_prompt_state_and_hello(self, isolated_swarm_env: Path) -> None:
        result = swarm_boot("zcode-1")
        assert result["ok"] is True
        assert result["agent_name"] == "zcode-1"
        assert "EVOLVER SWARM" in result["instrument_prompt"]
        assert result["state"]["version"] == "1.100.0"
        assert result["next_action"] == "swarm_tick"

        from evolver.proxy.mailbox.store import MailboxStore

        store = MailboxStore(isolated_swarm_env / ".evolver" / "proxy-mailbox")
        hello = [m for m in store.poll(limit=50) if m.type == "swarm.hello"]
        assert hello and hello[0].payload["agent"] == "zcode-1"

    def test_status_shape(self, isolated_swarm_env: Path) -> None:
        status = swarm_status()
        assert status["ok"] is True
        assert status["protocol_version"] == SWARM_PROTOCOL_VERSION
        assert status["workspace_root"] == str(isolated_swarm_env)
        # Bundled seed genes load even in a fresh store.
        assert status["genes"] >= 1
        assert status["pending_solidify"] is False
        assert set(status["mailbox_pending"]) == {"inbound", "outbound"}


class TestTick:
    async def test_tick_dispatches_and_captures_stdout(
        self, isolated_swarm_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = await swarm_tick(agent_name="tester")
        assert result["ok"] is True
        assert result["dispatch_reason"] == "dispatched"
        assert result["run_id"]
        assert "GENOME EVOLUTION PROTOCOL" in (result["dispatch_prompt"] or "")
        assert "Selected Gene" in result["engine_log"] or "BUILT_PROMPT" in result["engine_log"]
        assert result["next_action"] == "execute_prompt"
        # Stdout capture proof: nothing leaked past redirect_stdout.
        assert capsys.readouterr().out == ""

    async def test_tick_persists_state_and_leaves_solidify_pending(
        self, isolated_swarm_env: Path
    ) -> None:
        first = await swarm_tick()
        assert first["ok"] is True
        second = await swarm_tick()
        state_file = isolated_swarm_env / "evolution" / "swarm_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["ticks"] == 2
        assert data["last_tick"]["run_id"] == second["run_id"]
        # Solidify state written by dispatch → the loop's next step is pending.
        assert swarm_status()["pending_solidify"] is True

    async def test_tick_without_prompt(self, isolated_swarm_env: Path) -> None:
        result = await swarm_tick(include_prompt=False)
        assert result["ok"] is True
        assert result["dispatch_prompt"] is None


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
        assert result["next_action"] == "swarm_solidify"

        from evolver.gep.asset_store import load_genes

        assert any(g.get("id") == "gene_swarm_demo" for g in load_genes())

    def test_distill_empty_rejected(self, isolated_swarm_env: Path) -> None:
        result = swarm_distill("   ")
        assert result["ok"] is False
        assert result["error"] == "empty_response"

    def test_solidify_without_pending_run(self, isolated_swarm_env: Path) -> None:
        result = swarm_solidify()
        assert result["ok"] is False
        assert result["error"] == "no_pending_run"

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


class TestHitlGate:
    def test_mode_off_auto_approves_with_audit(self, isolated_swarm_env: Path) -> None:
        result = swarm_solidify(skip_validation=True, agent_name="tester")
        # Gate passed (auto-approved) — the engine itself then reports the
        # fresh workspace has no pending run.
        assert result.get("error") == "no_pending_run"
        journal = isolated_swarm_env / "evolution" / "hitl_approvals.jsonl"
        assert journal.exists() and "auto_approved" in journal.read_text(encoding="utf-8")

    def test_mode_on_blocks_until_approved(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.HITL_MODE", "on")
        blocked = swarm_solidify(skip_validation=True, agent_name="tester")
        assert blocked["ok"] is False
        assert blocked["error"] == "hitl_pending"
        assert blocked["next_action"] == "await_human_approval"

        from evolver.gep.hitl import resolve_approval

        request_id = blocked["approval"]["request_id"]
        assert resolve_approval(request_id, approve=True, decided_by="human")["ok"]

        passed = swarm_solidify(skip_validation=True, agent_name="tester")
        assert passed.get("error") == "no_pending_run"

    def test_mode_on_rejected_blocks(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.HITL_MODE", "on")
        blocked = swarm_solidify(skip_validation=True)
        from evolver.gep.hitl import resolve_approval

        resolve_approval(blocked["approval"]["request_id"], approve=False)
        again = swarm_solidify(skip_validation=True)
        assert again["error"] == "hitl_rejected"
        assert again["next_action"] == "swarm_tick"

    def test_status_exposes_hitl_state(self, isolated_swarm_env: Path) -> None:
        status = swarm_status()
        assert status["hitl"]["mode"] in ("on", "off")
        assert isinstance(status["hitl"]["pending"], int)
