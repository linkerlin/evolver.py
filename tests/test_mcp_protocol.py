"""MCP stdio protocol E2E — real subprocess, real JSON-RPC framing.

Locks in the contract the swarm depends on: initialize instructions carry the
swarm directive, tools/prompts/resources are discoverable, tool calls return
structured JSON, engine stdout never leaks into the protocol stream (stdio
MCP owns stdout), and invalid enum arguments get structured error feedback
instead of crashing the server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _server_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "EVOLVER_REPO_ROOT": str(tmp_path),
            "OPENCLAW_WORKSPACE": str(tmp_path),
            "GEP_ASSETS_DIR": str(tmp_path / "gep"),
            "EVOLUTION_DIR": str(tmp_path / "evolution"),
            "A2A_HUB_URL": "http://127.0.0.1:9",
            "EVOLVE_LOAD_MAX": "999",
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
            bufsize=1,
            cwd=str(tmp_path),
            env=_server_env(tmp_path),
        )
        self._id = 0
        self.init_result: dict = {}

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return self.recv()

    def send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line, "server closed the stream (crashed?)"
        return json.loads(line)  # stdout must contain ONLY JSON-RPC frames

    def call_tool(self, name: str, args: dict) -> dict:
        res = self.request("tools/call", {"name": name, "arguments": args})
        return json.loads(res["result"]["content"][0]["text"])

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def client(tmp_path: Path) -> _McpClient:
    c = _McpClient(tmp_path)
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


class TestProtocol:
    def test_instructions_carry_swarm_directive(self, client: _McpClient) -> None:
        instructions = client.init_result["result"]["instructions"]
        assert "SWARM EVOLUTION" in instructions
        assert "swarm_hook_event" in instructions
        assert "evolver://" in instructions

    def test_tools_list_has_swarm_surface(self, client: _McpClient) -> None:
        tools = client.request("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {
            "swarm_boot",
            "swarm_tick",
            "swarm_distill",
            "swarm_solidify",
            "swarm_feedback",
            "swarm_status",
            "swarm_supervise",
            "swarm_hooks",
            "swarm_hook_event",
        } <= names

    def test_read_only_annotations_present(self, client: _McpClient) -> None:
        tools = {t["name"]: t for t in client.request("tools/list")["result"]["tools"]}
        assert tools["swarm_status"]["annotations"]["readOnlyHint"] is True
        assert tools["swarm_solidify"]["annotations"]["destructiveHint"] is True

    def test_prompt_renders_takeover_protocol(self, client: _McpClient) -> None:
        prompts = {p["name"] for p in client.request("prompts/list")["result"]["prompts"]}
        assert "evolver_swarm" in prompts
        got = client.request(
            "prompts/get", {"name": "evolver_swarm", "arguments": {"agent_name": "e2e"}}
        )
        text = got["result"]["messages"][0]["content"]["text"]
        assert "EVOLVER SWARM" in text and "e2e" in text

    def test_resources_discoverable_and_readable(self, client: _McpClient) -> None:
        resources = {r["uri"]: r for r in client.request("resources/list")["result"]["resources"]}
        assert {
            "evolver://status",
            "evolver://instrument-prompt",
            "evolver://dispatch/last",
            "evolver://events/recent",
        } <= set(resources)

        status_text = client.request("resources/read", {"uri": "evolver://status"})["result"][
            "contents"
        ][0]["text"]
        status = json.loads(status_text)
        assert status["ok"] is True and status["version"] == "1.104.0"

        prompt_text = client.request("resources/read", {"uri": "evolver://instrument-prompt"})[
            "result"
        ]["contents"][0]["text"]
        assert "EVOLVER SWARM" in prompt_text

    def test_tool_call_round_trip(self, client: _McpClient, tmp_path: Path) -> None:
        status = client.call_tool("swarm_status", {})
        assert status["ok"] is True

        hook = client.call_tool(
            "swarm_hook_event",
            {"event": "signal_detect", "payload": {"content": "request timeout detected"}},
        )
        assert "perf_bottleneck" in hook["detected_signals"]
        pending = json.loads((tmp_path / "gep" / "pending_signals.json").read_text())
        assert "perf_bottleneck" in pending["signals"]

    def test_invalid_enum_gets_structured_feedback(self, client: _McpClient) -> None:
        res = client.request(
            "tools/call", {"name": "swarm_hook_event", "arguments": {"event": "bogus"}}
        )
        text = res["result"]["content"][0]["text"]
        assert text.startswith("Error executing tool")
        # The server must still be alive afterwards.
        assert client.call_tool("swarm_status", {})["ok"] is True

    def test_supervise_pause_resume_over_wire(self, client: _McpClient) -> None:
        paused = client.call_tool("swarm_supervise", {"action": "pause", "reason": "e2e"})
        assert paused["state"] == "paused"
        status = client.call_tool("swarm_status", {})
        assert status["supervision"]["state"] == "paused"
        resumed = client.call_tool("swarm_supervise", {"action": "resume"})
        assert resumed["state"] == "running"
