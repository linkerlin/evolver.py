"""Full-coverage swarm E2E over real stdio MCP — two tiers.

Tier A (always runs): walks the ENTIRE MCP surface against a real server
subprocess — every swarm tool, every classic tool, all four resources, the
evolver_swarm prompt, the auto-hijack instructions variant, HITL/HOTL flows,
the skills bridge, and the invalid-enum error path.

Tier B (@pytest.mark.llm, requires DEEPSEEK_API_KEY): a REAL LLM joins the
loop — DeepSeek (deepseek-v4-flash) plays the host executor: it receives the
GEP dispatch prompt from swarm_tick, produces work output + a valid Gene
block, which flows through swarm_distill → swarm_feedback → a second tick.
This validates the takeover contract end-to-end with an actual model, while
keeping the engine itself LLM-free (the client lives in the test harness).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

DEMO_SKILL_MD = """---
name: demo-skill
description: Fix ImportError problems in Python imports quickly
---
# Demo skill

- step one
- step two
"""


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _workspace_env(ws: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "EVOLVER_REPO_ROOT": str(ws),
            "OPENCLAW_WORKSPACE": str(ws),
            "GEP_ASSETS_DIR": str(ws / "gep"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "EVOLVER_USER_LOCK": str(ws / "user.lock"),
            "A2A_HUB_URL": "http://127.0.0.1:9",
            "EVOLVE_LOAD_MAX": "999",
            "EVOLVER_SKILL_ROOTS": str(ws / "skill-roots"),
        }
    )
    return env


class _McpClient:
    """Minimal stdio JSON-RPC client for one MCP server subprocess."""

    def __init__(self, cwd: Path, extra_env: dict[str, str] | None = None) -> None:
        env = _workspace_env(cwd)
        env.update(extra_env or {})
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "evolver.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(cwd),
            env=env,
        )
        self._id = 0
        self.init_result: dict[str, Any] = {}
        self.init_result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "0"},
            },
        )
        assert self.init_result["result"]["serverInfo"]["name"] == "evolver"
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line, "server closed the stream (crashed?)"
        return json.loads(line)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return self.recv()

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": args or {}})["result"]
        # Prefer the MCP structured-output channel (the spec requires a
        # top-level object, so the SDK wraps non-dict returns as
        # {"result": ...}; content[].text only carries a list's first item).
        structured = result.get("structuredContent")
        if structured is not None:
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        return json.loads(result["content"][0]["text"])

    def call_raw_text(self, name: str, args: dict[str, Any] | None = None) -> str:
        res = self.request("tools/call", {"name": name, "arguments": args or {}})
        return str(res["result"]["content"][0]["text"])

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def e2e_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "e2e@t"],
        ["git", "config", "user.name", "e2e"],
    ):
        subprocess.run(cmd, cwd=ws, check=True, capture_output=True)
    (ws / "README.md").write_text("# e2e workspace\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init", "--allow-empty"],
        cwd=ws,
        check=True,
        capture_output=True,
    )
    skill = ws / "skill-roots" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(DEMO_SKILL_MD, encoding="utf-8")
    return ws


@pytest.fixture
def client(e2e_ws: Path) -> _McpClient:
    c = _McpClient(e2e_ws)
    yield c
    c.close()


def _deepseek_chat(system: str, user: str, max_tokens: int = 4000) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not set — live-LLM loop e2e skipped")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    last_error: Exception | None = None
    for attempt in range(2):  # transient API hiccups must not flake the e2e
        if attempt:
            time.sleep(2.0)
        try:
            resp = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"] or "")
        except (httpx.HTTPError, KeyError) as exc:
            last_error = exc
    raise AssertionError(f"DeepSeek call failed after retries: {last_error!r}")


# ---------------------------------------------------------------------------
# Tier A — full-surface E2E (deterministic, no LLM)
# ---------------------------------------------------------------------------


class TestFullSurfaceE2E:
    def test_01_boot_status_and_resources(self, client: _McpClient, e2e_ws: Path) -> None:
        assert "SWARM EVOLUTION" in client.init_result["result"]["instructions"]

        boot = client.call("swarm_boot", {"agent_name": "e2e-worker"})
        assert boot["ok"] is True
        assert "EVOLVER SWARM" in boot["instrument_prompt"]
        assert boot["next_action"] == "swarm_tick"

        status = client.call("swarm_status", {})
        for key in ("version", "supervision", "hitl", "feedback", "mailbox_pending", "genes"):
            assert key in status

        for uri, needle in (
            ("evolver://status", '"ok"'),
            ("evolver://instrument-prompt", "EVOLVER SWARM"),
            ("evolver://dispatch/last", None),
            ("evolver://events/recent", None),
        ):
            text = client.request("resources/read", {"uri": uri})["result"]["contents"][0]["text"]
            assert isinstance(text, str) and text
            if needle:
                assert needle in text

    def test_02_prompt_and_hooks(self, client: _McpClient, e2e_ws: Path) -> None:
        got = client.request(
            "prompts/get", {"name": "evolver_swarm", "arguments": {"agent_name": "e2e-prompt"}}
        )
        text = got["result"]["messages"][0]["content"]["text"]
        assert "e2e-prompt" in text and "swarm_tick" in text

        hook = client.call(
            "swarm_hook_event",
            {"event": "signal_detect", "payload": {"content": "request timeout after retry"}},
        )
        assert "perf_bottleneck" in hook["detected_signals"]
        pending = json.loads((e2e_ws / "gep" / "pending_signals.json").read_text())
        assert "perf_bottleneck" in pending["signals"]

    def test_03_skills_bridge_end_to_end(self, client: _McpClient, e2e_ws: Path) -> None:
        scan = client.call("swarm_skills", {"action": "scan"})
        assert any(s["name"] == "demo-skill" for s in scan["skills"])

        dry = client.call("swarm_skills", {"action": "sync", "dry_run": True})
        assert dry["dry_run"] is True

        synced = client.call("swarm_skills", {"action": "sync"})
        assert any(i["name"] == "demo-skill" for i in synced["installed"])

        listed = client.call("swarm_skills", {"action": "list"})
        assert any(g["skill_name"] == "demo-skill" for g in listed["genes"])

        # The skill gene is searchable through the classic asset tools too.
        hits = client.call("tool_asset_search", {"query": "demo-skill"})
        assert any(h.get("id") == "gene_distilled_s2g-demo-skill" for h in hits)
        one = client.call("tool_asset_get", {"asset_id": "gene_distilled_s2g-demo-skill"})
        assert one["type"] == "Gene"

    def test_04_mailbox_and_events(self, client: _McpClient) -> None:
        sent = client.call(
            "tool_mailbox_send", {"type": "e2e.note", "payload": {"hi": 1}, "priority": "high"}
        )
        assert sent["status"] in ("pending", "queued", "new")
        outbound = client.call("tool_mailbox_poll", {"direction": "outbound"})
        assert any(m["id"] == sent["message_id"] for m in outbound)

        # ack applies to the INBOUND queue only (outbound is our own pending
        # sends): swarm_boot's hello lands inbound → poll + ack round trip.
        client.call("swarm_boot", {"agent_name": "e2e-mailbox"})
        inbound = client.call("tool_mailbox_poll", {"direction": "inbound"})
        hellos = [m for m in inbound if m.get("type") == "swarm.hello"]
        assert hellos
        assert client.call("tool_mailbox_ack", {"message_ids": [hellos[0]["id"]]}) == 1
        assert client.call("tool_mailbox_ack", {"message_ids": [sent["message_id"]]}) == 0

        assert client.call("tool_cycle_timeline", {}) == []
        views = client.call("tool_rebuild_views", {})
        assert "event_count" in views and "cycles" in views

    def test_05_tick_distill_and_gates(self, client: _McpClient) -> None:
        tick = client.call("swarm_tick", {"agent_name": "e2e-worker"})
        assert tick["ok"] is True
        assert tick.get("paused") is not True
        assert tick["dispatch_reason"] in ("dispatched", "idle_cycle", "no_gene_selected")
        if tick["dispatch_reason"] == "dispatched":
            assert "GENOME EVOLUTION PROTOCOL" in (tick["dispatch_prompt"] or "")

        response = (
            "Executed mutation. Extracted asset:\n```json\n"
            '{"type": "Gene", "id": "gene_e2e_surface", "category": "repair", '
            '"summary": "surface e2e gene", "signals_match": ["ImportError"]}\n'
            "```\n"
        )
        distilled = client.call("swarm_distill", {"response_text": response})
        assert distilled["ok"] is True and distilled["genes"] == 1

        # Solidify gate runs and returns a structured outcome either way
        # (fresh repo, no real mutation → gate verdict, never a crash).
        solidified = client.call("swarm_solidify", {})
        assert isinstance(solidified, dict)
        assert solidified.get("ok") is not None or solidified.get("error")

        report = client.call(
            "swarm_report", {"category": "friction", "description": "e2e", "resolution": "none"}
        )
        assert report["ok"] is True

        feedback = client.call(
            "swarm_feedback",
            {
                "primary_score": 0.2,
                "textual_gradient": "surface e2e degraded on purpose",
                "agent_name": "e2e-worker",
            },
        )
        assert feedback["degraded"] is True

    def test_06_hitl_and_supervision_flows(self, client: _McpClient) -> None:
        # HITL mode=off: auto-approve journaled.
        risky = client.call("swarm_solidify", {"skip_validation": True})
        assert risky.get("error") != "hitl_pending"

        approvals = client.call("swarm_approvals", {})
        assert "pending" in approvals and "recent" in approvals
        unknown = client.call(
            "swarm_approval_resolve", {"request_id": "hitl_none", "approve": True}
        )
        assert unknown["ok"] is False

        # HOTL: pause blocks ticks; directives inject signals; veto blocks solidify.
        assert (
            client.call("swarm_supervise", {"action": "pause", "reason": "e2e"})["state"]
            == "paused"
        )
        paused_tick = client.call("swarm_tick", {})
        assert paused_tick.get("paused") is True
        assert client.call("swarm_supervise", {"action": "resume"})["state"] == "running"

        directive = client.call("swarm_supervise", {"action": "direct", "text": "e2e steering"})
        assert directive["ok"] is True

        veto = client.call("swarm_supervise", {"action": "veto", "pattern": "solidify:"})
        blocked = client.call("swarm_solidify", {})
        assert blocked["error"] == "supervision_veto"
        assert client.call("swarm_supervise", {"action": "unveto", "veto_id": veto["veto_id"]})[
            "ok"
        ]

        assert (
            client.call("swarm_supervise", {"action": "status"})["supervision"]["state"]
            == "running"
        )

    def test_07_invalid_input_structured_feedback(self, client: _McpClient) -> None:
        text = client.call_raw_text("swarm_hook_event", {"event": "bogus"})
        assert text.startswith("Error executing tool")
        assert client.call("swarm_status", {})["ok"] is True  # server survived

    def test_08_auto_hijack_instructions_variant(self, e2e_ws: Path) -> None:
        hijacked = _McpClient(e2e_ws, extra_env={"EVOLVER_SWARM_AUTO_HIJACK": "1"})
        try:
            instructions = hijacked.init_result["result"]["instructions"]
            assert "TAKEOVER ACTIVE" in instructions
            assert "SWARM EVOLUTION" in instructions
        finally:
            hijacked.close()


# ---------------------------------------------------------------------------
# Tier B — live LLM loop E2E (DeepSeek as the host executor)
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """You are the executor of the EVOLVER SWARM loop (a real
self-evolution engine). You receive a GEP (Genome Evolution Protocol)
dispatch prompt. This run is sandboxed: do NOT attempt file edits yourself.

Your reply MUST contain, in order:
1. A short work summary (what the mutation would do).
2. Exactly ONE fenced ```json block containing a single valid Gene object
with EXACTLY these keys (no extras — the schema forbids unknown fields):
{"type": "Gene", "id": "gene_e2e_llm", "category": "repair",
 "summary": "<one line>", "signals_match": ["<one signal keyword>"],
 "strategy": ["<step>"], "preconditions": [], "validation": ["python --version"],
 "avoid": []}
Replace <...> with content grounded in the dispatch prompt."""


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestLiveLlmLoopE2E:
    def test_full_loop_with_deepseek(self, client: _McpClient, e2e_ws: Path) -> None:
        # Arrange: seed the loop with signals and a skill gene.
        client.call(
            "swarm_hook_event",
            {"event": "signal_detect", "payload": {"content": "ImportError: cannot import name"}},
        )
        client.call("swarm_skills", {"action": "sync"})

        # Act 1: tick → GEP dispatch prompt.
        tick = client.call("swarm_tick", {"agent_name": "deepseek-executor"})
        assert tick["ok"] is True
        if tick["dispatch_reason"] not in ("dispatched", "idle_cycle"):
            pytest.skip(f"no dispatch this cycle: {tick['dispatch_reason']}")
        dispatch_prompt = tick.get("dispatch_prompt") or ""
        if not dispatch_prompt:
            pytest.skip("idle cycle — no prompt to execute")

        # Act 2: the real LLM executes the dispatch prompt.
        response = _deepseek_chat(_LLM_SYSTEM, dispatch_prompt)
        assert len(response.strip()) > 40, f"empty LLM response: {response[:200]!r}"

        # Act 3: distill the LLM output (one strict retry if the contract
        # was violated on the first attempt).
        distilled = client.call("swarm_distill", {"response_text": response})
        if distilled["genes"] + distilled["capsules"] + distilled["mutations"] == 0:
            retry = _deepseek_chat(
                _LLM_SYSTEM
                + "\n\nYour previous reply violated the output contract. Output ONLY the "
                "summary and the single fenced json Gene block.",
                dispatch_prompt,
            )
            distilled = client.call("swarm_distill", {"response_text": retry})
        assert distilled["ok"] is True
        assert distilled["genes"] + distilled["capsules"] > 0, (
            f"LLM produced no distillable assets; response head: {response[:300]!r}"
        )

        # Act 4: feedback with a gradient grounded in the LLM summary.
        summary_head = response.strip().splitlines()[0][:120]
        feedback = client.call(
            "swarm_feedback",
            {
                "primary_score": 0.85,
                "textual_gradient": f"deepseek executor: {summary_head}",
                "agent_name": "deepseek-executor",
                "run_id": tick.get("run_id"),
                "cycle_id": tick.get("cycle_id"),
            },
        )
        assert feedback["ok"] is True and feedback["degraded"] is False

        # Assert: journals + status reflect the whole round trip.
        feedback_journal = e2e_ws / "memory" / "evolution" / "feedback.jsonl"
        assert "deepseek executor" in feedback_journal.read_text(encoding="utf-8")

        status = client.call("swarm_status", {})
        assert status["feedback"]["recent_count"] >= 1
        assert status["feedback"]["last"]["primary_score"] == 0.85

        # Act 5: the loop continues — a second tick still works.
        second = client.call("swarm_tick", {"agent_name": "deepseek-executor"})
        assert second["ok"] is True
        assert second.get("paused") is not True

    def test_llm_reports_signal_from_error_output(self, client: _McpClient) -> None:
        """The LLM also plays the hook bridge: it classifies an error log."""
        log_line = "TypeError: cannot read properties of undefined (reading 'map')"
        response = _deepseek_chat(
            "Classify the error in the user's log. Reply with ONE word: "
            "import_error, type_error, runtime_error, or network_error.",
            log_line,
            max_tokens=512,
        )
        verdict = response.strip().lower()
        assert any(
            tag in verdict
            for tag in ("import_error", "type_error", "runtime_error", "network_error")
        ), response[:120]
