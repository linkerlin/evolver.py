"""MCP stdio protocol E2E — real subprocess, real JSON-RPC framing (算子即基因 P1-1).

Verifies the dynamic FSM 3-tool atomic MCP protocol end-to-end:
- Connect-time instructions present the concise 3-tool FSM protocol (zero legacy
  6-step swarm_* ceremony or whack-a-mole redirect flags);
- ``IDLE`` ``tools/list`` exposes ``evolve_begin`` + ``evolve_status`` and hides
  ``run_lens`` + ``evolve_settle``;
- Calling ``run_lens`` or ``evolve_settle`` in ``IDLE`` returns structured
  ``error="fsm_state_mismatch"`` (``isError=True``);
- ``evolve_begin()`` with empty hypothesis and ``auto_discover=True`` previews
  signals & candidate operators while staying in ``IDLE``;
- ``evolve_begin(hypothesis="...")`` locks the hypothesis, transitions to
  ``ACTIVE_RUN``, emits ``notifications/tools/list_changed``, hides
  ``evolve_begin``, and exposes ``run_lens`` + ``evolve_settle``;
- Calling ``evolve_begin`` while ``ACTIVE_RUN`` is blocked with
  ``error="fsm_state_mismatch"``;
- ``run_lens`` executes read-only AST/impact diagnostics and records into the
  active cycle blackbox;
- ``evolve_settle(summary="...")`` validates, settles blackbox + episode_record,
  emits ``notifications/tools/list_changed``, and returns ``tools/list`` to ``IDLE``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver import __version__
from tests.mcp_surface import (
    MCP_ACTIVE_TOOL_NAMES,
    MCP_IDLE_TOOL_NAMES,
    MCP_PROMPT_NAMES,
    MCP_RESOURCE_URIS,
)


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "mcp@evolver.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "MCP Test"], cwd=repo, check=True)
    (repo / "service.py").write_text(
        "def clamp(x: int) -> int:\n    return max(0, x)\n", encoding="utf-8"
    )
    (repo / "test_service.py").write_text(
        "from service import clamp\n\ndef test_clamp() -> None:\n    assert clamp(-3) == 0\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )


def _server_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "EVOLVER_REPO_ROOT": str(tmp_path),
            "OPENCLAW_WORKSPACE": str(tmp_path),
            "GEP_ASSETS_DIR": str(tmp_path / ".state" / "gep"),
            "EVOLUTION_DIR": str(tmp_path / ".state" / "evolution"),
            "EVOLVER_STATE_ROOT": str(tmp_path / ".state"),
            "A2A_HUB_URL": "http://127.0.0.1:9",
            "EVOLVE_LOAD_MAX": "999",
            "EVOLVER_HOME": str(tmp_path / ".evomap"),
        }
    )
    return env


class _McpClient:
    def __init__(self, tmp_path: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "evolver.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(tmp_path),
            env=_server_env(tmp_path),
        )
        self._id = 0
        self.init_result: dict[str, Any] = {}
        self.notifications: list[dict[str, Any]] = []

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return self.recv()

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            assert line, "server closed the stream (crashed?)"
            msg = json.loads(line)  # stdout must contain ONLY JSON-RPC frames
            if "id" not in msg and str(msg.get("method") or "").startswith("notifications/"):
                self.notifications.append(msg)
                continue
            return msg

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": args})["result"]
        structured = result.get("structuredContent")
        if structured is not None:
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        return json.loads(result["content"][0]["text"])

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def client(tmp_path: Path) -> _McpClient:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    c = _McpClient(repo)
    c.init_result = c.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    )
    assert c.init_result["result"]["serverInfo"]["name"] == "evolver"
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    yield c
    c.close()


class TestFsmThreeToolProtocol:
    def test_instructions_carry_concise_fsm_directive(self, client: _McpClient) -> None:
        instructions = client.init_result["result"]["instructions"]
        assert "EVOLVER SWARM" in instructions
        assert "evolve_begin" in instructions
        assert "run_lens" in instructions
        assert "evolve_settle" in instructions
        assert len(instructions) < 900
        for legacy in (
            "swarm_boot",
            "swarm_tick",
            "swarm_distill",
            "swarm_solidify",
            "loop_fuse",
            "gate_soft_continue",
            "pending_redirect_loop",
        ):
            assert legacy not in instructions

    def test_idle_surface_and_annotations(self, client: _McpClient) -> None:
        tools_cap = client.init_result["result"]["capabilities"]["tools"]
        assert tools_cap["listChanged"] is True

        listed = client.request("tools/list")["result"]
        assert listed.get("nextCursor") in (None, "")
        tools_by_name = {t["name"]: t for t in listed["tools"]}
        assert set(tools_by_name) == set(MCP_IDLE_TOOL_NAMES)
        assert "run_lens" not in tools_by_name
        assert "evolve_settle" not in tools_by_name
        assert tools_by_name["evolve_status"]["annotations"]["readOnlyHint"] is True

        prompts = client.request("prompts/list")["result"]["prompts"]
        assert {p["name"] for p in prompts} == set(MCP_PROMPT_NAMES)
        resources = client.request("resources/list")["result"]["resources"]
        assert {r["uri"] for r in resources} == set(MCP_RESOURCE_URIS)

        methods = {note.get("method") for note in client.notifications}
        assert "notifications/tools/list_changed" in methods

    def test_idle_blocks_active_only_tools(self, client: _McpClient) -> None:
        res_lens = client.request("tools/call", {"name": "run_lens", "arguments": {}})["result"]
        assert res_lens.get("isError") is True
        body_lens = json.loads(res_lens["content"][0]["text"])
        assert body_lens["ok"] is False
        assert body_lens["error"] == "fsm_state_mismatch"
        assert body_lens["fsm_state"] == "IDLE"

        res_settle = client.request("tools/call", {"name": "evolve_settle", "arguments": {}})[
            "result"
        ]
        assert res_settle.get("isError") is True
        body_settle = json.loads(res_settle["content"][0]["text"])
        assert body_settle["error"] == "fsm_state_mismatch"

    def test_full_fsm_begin_lens_settle_lifecycle_with_list_changed(
        self, client: _McpClient, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"

        # 0. Cold status and zero-side-effect signal/operator discovery
        status0 = client.call_tool("evolve_status", {})
        assert status0["ok"] is True
        assert status0["fsm_state"] == "IDLE"
        assert status0["next_action"] == "evolve_begin"

        preview = client.call_tool("evolve_begin", {"hypothesis": "", "auto_discover": True})
        assert preview["ok"] is True
        assert preview["discovery_only"] is True
        assert preview["fsm_state"] == "IDLE"

        empty_err = client.call_tool("evolve_begin", {"hypothesis": "", "auto_discover": False})
        assert empty_err["ok"] is False
        assert empty_err["error"] == "empty_hypothesis"

        # 1. Start atomic run -> transitions IDLE -> ACTIVE_RUN + emits list_changed
        notes_before_begin = len(client.notifications)
        began = client.call_tool(
            "evolve_begin",
            {
                "hypothesis": "Extend clamp helper in service.py to upper-bound values at 100.",
                "target_files": ["service.py"],
            },
        )
        assert began["ok"] is True
        assert began["fsm_state"] == "ACTIVE_RUN"
        assert began["run_id"]
        assert len(client.notifications) > notes_before_begin

        # 2. Verify ACTIVE_RUN catalog hides evolve_begin & exposes run_lens/evolve_settle
        active_tools = {t["name"]: t for t in client.request("tools/list")["result"]["tools"]}
        assert set(active_tools) == set(MCP_ACTIVE_TOOL_NAMES)
        assert "evolve_begin" not in active_tools
        assert active_tools["run_lens"]["annotations"]["readOnlyHint"] is True
        assert active_tools["evolve_settle"]["annotations"]["destructiveHint"] is True

        # 3. Duplicate evolve_begin while ACTIVE_RUN is hard-blocked
        dup = client.request(
            "tools/call",
            {"name": "evolve_begin", "arguments": {"hypothesis": "duplicate attempt"}},
        )["result"]
        assert dup.get("isError") is True
        assert json.loads(dup["content"][0]["text"])["error"] == "fsm_state_mismatch"

        # 3b. Explicit force_takeover=True replaces the active run through MCP guard
        taken = client.call_tool(
            "evolve_begin",
            {
                "hypothesis": "Take over active run via explicit force_takeover",
                "force_takeover": True,
                "auto_discover": False,
            },
        )
        assert taken["ok"] is True
        assert taken["taken_over"] is True
        assert taken["run_id"] != began["run_id"]

        # 4. Run lenses in ACTIVE_RUN -> recorded into active blackbox
        lens_res = client.call_tool("run_lens", {"name": "import_impact", "target": "service.py"})
        assert lens_res["ok"] is True
        assert "test_service.py" in lens_res["impacted_tests"]

        status_active = client.call_tool("evolve_status", {})
        assert status_active["fsm_state"] == "ACTIVE_RUN"
        assert status_active["active_blackbox"]["lens_calls_count"] == 1

        # 5. Apply edit in workspace and settle
        (repo / "service.py").write_text(
            "def clamp(x: int, hi: int = 100) -> int:\n    return min(hi, max(0, x))\n",
            encoding="utf-8",
        )
        notes_before_settle = len(client.notifications)
        settled = client.call_tool(
            "evolve_settle",
            {"summary": "Added optional hi upper bound to clamp()"},
        )
        assert settled["fsm_state"] == "IDLE"
        assert settled["blackbox"]["lens_calls_count"] == 1
        assert settled["episode_id"].startswith("sha256:")
        assert len(client.notifications) > notes_before_settle

        # 6. Catalog automatically reverted to IDLE
        idle_again = {t["name"] for t in client.request("tools/list")["result"]["tools"]}
        assert idle_again == set(MCP_IDLE_TOOL_NAMES)

        # Episode record is readable via episode_get and carries blackbox telemetry
        ep = client.call_tool("episode_get", {"episode_id": settled["episode_id"]})
        assert ep["gates"]["blackbox"]["lens_calls_count"] == 1

    def test_prompt_resources_and_invalid_enum_handling(self, client: _McpClient) -> None:
        got = client.request(
            "prompts/get", {"name": "evolver_swarm", "arguments": {"agent_name": "e2e"}}
        )
        text = got["result"]["messages"][0]["content"]["text"]
        assert "EVOLVER SWARM" in text and "e2e" in text and "evolve_begin" in text

        status_text = client.request("resources/read", {"uri": "evolver://status"})["result"][
            "contents"
        ][0]["text"]
        status = json.loads(status_text)
        assert status["ok"] is True and status["version"] == __version__

        empty = client.call_tool("tool_asset_search", {"query": "zzz_no_such_asset"})
        assert empty["ok"] is True and empty["items"] == [] and empty["hint"]
