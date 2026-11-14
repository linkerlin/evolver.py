"""Full-coverage swarm E2E over real stdio MCP — two tiers (v1.114.0 FSM surface).

Tier A (always runs): walks the ENTIRE FSM-gated MCP surface against a real server
subprocess — dynamic `IDLE` vs `ACTIVE_RUN` catalog gating with
`notifications/tools/list_changed`, `evolve_status`, `evolve_begin` (preview +
hypothesis lock), `run_lens` (read-only AST/impact/traceback diagnostics),
`evolve_settle` (L0 lightning check, blackbox + immutable `episode_record`,
`draft_preserved` vs `promoted`), all read-only auxiliary tools (`episode_get`,
`episode_inspect`, `tool_asset_search`, `tool_asset_get`, `tool_cycle_timeline`),
all four resources, the `evolver_swarm` prompt, PreCompact hook checkpoint
interoperability, and structured invalid-argument handling.

Tier B (@pytest.mark.llm, requires DEEPSEEK_API_KEY): a REAL LLM joins the loop
as the host executor driving `evolve_begin` -> edit -> `evolve_settle`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.mcp_surface import MCP_ACTIVE_TOOL_NAMES, MCP_IDLE_TOOL_NAMES

DEMO_SKILL_MD = """---
name: demo-skill
description: Fix ImportError problems in Python imports quickly
---
# Demo skill

- step one
- step two
"""


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
            "EVOLVER_HOME": str(ws / ".evomap"),
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
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(cwd),
            env=env,
        )
        self._id = 0
        self.notifications: list[dict[str, Any]] = []
        self.init_result: dict[str, Any] = self.request(
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
        while True:
            line = self.proc.stdout.readline()
            assert line, "server closed the stream (crashed?)"
            msg = json.loads(line)
            if "id" not in msg and str(msg.get("method") or "").startswith("notifications/"):
                self.notifications.append(msg)
                continue
            return msg

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        expected = self._id
        self.send({"jsonrpc": "2.0", "id": expected, "method": method, "params": params or {}})
        msg = self.recv()
        assert msg.get("id") == expected, msg
        return msg

    def list_tool_names(self) -> list[str]:
        res = self.request("tools/list")
        return [t["name"] for t in res["result"]["tools"]]

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": args or {}})["result"]
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
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init", "--allow-empty"],
        cwd=ws,
        check=True,
        capture_output=True,
    )
    skill = ws / ".claude" / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(DEMO_SKILL_MD, encoding="utf-8")
    return ws


@pytest.fixture
def client(e2e_ws: Path) -> Iterator[_McpClient]:
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
    for attempt in range(2):
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


_PASSING_TEST = """from app import add


def test_add() -> None:
    assert add(1, 1) == 2
"""

_LONG_FAILURE = """from app import add


def test_long_failure() -> None:
    assert add(1, 1) == 2
    print("\\n".join(f"diag-line-{i:03d}" for i in range(60)))
    print("TAIL-NEEDLE")
    raise AssertionError("compound case still broken")
"""

_SANDBOX_PROJECT = """[project]
name = "e2e-sandbox"
version = "0.0.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
"""

_SANDBOX_APP = """def add(left: int, right: int) -> int:
    return left + right
"""


def _commit_all(ws: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message],
        cwd=ws,
        check=True,
        capture_output=True,
    )


def _commit_python_project(ws: Path) -> None:
    (ws / "pyproject.toml").write_text(_SANDBOX_PROJECT, encoding="utf-8")
    (ws / "src").mkdir(exist_ok=True)
    (ws / "src" / "app.py").write_text(_SANDBOX_APP, encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "test_app.py").write_text(_PASSING_TEST, encoding="utf-8")
    _commit_all(ws, "seed a passing project")


def _run_precompact_hook(ws: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "evolver.adapters.scripts.compact_checkpoint"],
        cwd=ws,
        env=_workspace_env(ws),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# Tier A — full-surface E2E (deterministic, no LLM)
# ---------------------------------------------------------------------------


class TestFullSurfaceE2E:
    def test_00_list_changed_and_idle_catalog(self, client: _McpClient) -> None:
        names = client.list_tool_names()
        assert set(names) == set(MCP_IDLE_TOOL_NAMES)
        assert "evolve_begin" in names
        assert "run_lens" not in names
        assert "evolve_settle" not in names

        prompt = client.request(
            "prompts/get",
            {"name": "evolver_swarm", "arguments": {"agent_name": "e2e-notify"}},
        )
        assert "result" in prompt
        assert "EVOLVER SWARM" in prompt["result"]["messages"][0]["content"]["text"]
        methods = {note.get("method") for note in client.notifications}
        assert "notifications/tools/list_changed" in methods

    def test_01_status_resources_and_discovery_preview(
        self, client: _McpClient, e2e_ws: Path
    ) -> None:
        _ = e2e_ws
        assert "EVOLVER SWARM" in client.init_result["result"]["instructions"]
        assert len(client.init_result["result"]["instructions"]) < 600

        status = client.call("evolve_status", {})
        assert status["ok"] is True
        assert status["fsm_state"] == "IDLE"
        assert status["allowed_tools"] == ["evolve_begin", "evolve_status"]
        assert status["next_action"] == "evolve_begin"

        preview = client.call("evolve_begin", {"hypothesis": "", "auto_discover": True})
        assert preview["ok"] is True
        assert preview["discovery_only"] is True
        assert preview["fsm_state"] == "IDLE"
        assert "hypothesis_template" in preview

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

    def test_02_auxiliary_asset_and_timeline_tools(
        self, client: _McpClient, e2e_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEP_ASSETS_DIR", str(e2e_ws / "gep"))
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(e2e_ws))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(e2e_ws))
        from evolver.gep import skill_assets

        synced = skill_assets.sync_skills(dry_run=False)
        assert any(i["name"] == "demo-skill" for i in synced["installed"])

        hits = client.call("tool_asset_search", {"query": "demo-skill"})
        assert hits["ok"] is True
        assert any(h.get("id") == "gene_distilled_s2g-demo-skill" for h in hits["items"])

        missed = client.call("tool_asset_search", {"query": "zzz_no_such_asset"})
        assert missed["ok"] is True and missed["items"] == [] and missed["hint"]

        one = client.call("tool_asset_get", {"asset_id": "gene_distilled_s2g-demo-skill"})
        assert one["type"] == "Gene"

        timeline = client.call("tool_cycle_timeline", {})
        assert timeline["ok"] is True and timeline["items"] == [] and timeline["hint"]

    def test_03_fsm_begin_lens_settle_green_roundtrip(
        self, client: _McpClient, e2e_ws: Path
    ) -> None:
        _commit_python_project(e2e_ws)

        # Calling ACTIVE_RUN-only tool while IDLE returns structured fsm_state_mismatch
        early_settle = client.call("evolve_settle", {"summary": "too early"})
        assert early_settle["ok"] is False
        assert early_settle["error"] == "fsm_state_mismatch"
        assert early_settle["fsm_state"] == "IDLE"

        notif_before = len(client.notifications)
        begun = client.call(
            "evolve_begin",
            {
                "hypothesis": "Add subtract helper to app.py and cover with unit test",
                "target_files": ["src/app.py"],
                "agent_name": "e2e-worker",
            },
        )
        assert begun["ok"] is True
        assert begun["fsm_state"] == "ACTIVE_RUN"
        assert begun["run_id"]

        # Catalog dynamically switched to ACTIVE_RUN and pushed list_changed
        active_names = client.list_tool_names()
        assert set(active_names) == set(MCP_ACTIVE_TOOL_NAMES)
        assert len(client.notifications) > notif_before

        # Calling evolve_begin again during ACTIVE_RUN is blocked by hard FSM guard
        dup_begin = client.call("evolve_begin", {"hypothesis": "duplicate"})
        assert dup_begin["ok"] is False
        assert dup_begin["error"] == "fsm_state_mismatch"

        impact = client.call("run_lens", {"name": "import_impact", "target": "src/app.py"})
        assert impact["ok"] is True
        assert impact["read_only"] is True
        assert "tests/test_app.py" in impact["impacted_tests"]

        (e2e_ws / "src" / "app.py").write_text(
            _SANDBOX_APP
            + "\ndef subtract(left: int, right: int) -> int:\n    return left - right\n",
            encoding="utf-8",
        )
        (e2e_ws / "tests" / "test_app.py").write_text(
            "from app import add, subtract\n\n\n"
            "def test_add() -> None:\n"
            "    assert add(1, 1) == 2\n\n\n"
            "def test_sub() -> None:\n"
            "    assert subtract(5, 2) == 3\n",
            encoding="utf-8",
        )

        settled = client.call("evolve_settle", {"summary": "Added subtract helper and unit test"})
        assert settled["ok"] is True, settled
        assert settled["fsm_state"] == "IDLE"
        assert settled["next_action"] == "evolve_begin"
        assert settled.get("episode_id")
        assert settled.get("blackbox", {}).get("lens_calls_count") == 1

        # Catalog switched back to IDLE
        assert set(client.list_tool_names()) == set(MCP_IDLE_TOOL_NAMES)

        ep_body = client.call("episode_get", {"episode_id": settled["episode_id"]})
        assert ep_body["run_id"] == begun["run_id"]
        assert ep_body["gates"]["blackbox"]["lens_calls_count"] == 1

    def test_04_invalid_lookup_structured_feedback(self, client: _McpClient) -> None:
        missing = json.loads(client.call_raw_text("episode_get", {"episode_id": "sha256:nope"}))
        assert missing["ok"] is False
        assert missing["error"] == "not_found"
        assert missing["next_steps"]
        assert client.call("evolve_status", {})["ok"] is True

    def test_05_precompact_hook_and_begin_auto_checkpoint(
        self, client: _McpClient, e2e_ws: Path
    ) -> None:
        """PreCompact hook blocks once, and evolve_begin auto-satisfies the checkpoint."""
        first = _run_precompact_hook(e2e_ws)
        assert first["decision"] == "block"

        begun = client.call(
            "evolve_begin",
            {"hypothesis": "Preserve active hypothesis across context compaction"},
        )
        assert begun["ok"] is True
        assert begun["fsm_state"] == "ACTIVE_RUN"
        # evolve_begin wrote WORKING_SESSION.md and cleared the compaction gate
        assert _run_precompact_hook(e2e_ws) == {}

        st = client.call("evolve_status", {})
        assert st["working_session"]["exists"] is True
        assert "Preserve active hypothesis" in st["working_session"]["preview"]

    def test_06_draft_preserved_failure_and_episode_inspect(
        self, client: _McpClient, e2e_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Red test settles as draft_preserved with 3-line fix, intact patch, and inspect."""
        _commit_python_project(e2e_ws)
        begun = client.call(
            "evolve_begin",
            {
                "hypothesis": "Verify failing test settles as draft_preserved",
                "target_files": ["tests/test_app.py"],
            },
        )
        assert begun["ok"] is True

        (e2e_ws / "tests" / "test_app.py").write_text(_LONG_FAILURE, encoding="utf-8")

        settled = client.call("evolve_settle", {"summary": "Triggered long failure"})
        assert settled["ok"] is False, settled
        assert settled["outcome"] == "draft_preserved", settled
        assert settled["fsm_state"] == "IDLE"
        fix = settled.get("actionable_fix") or []
        assert len(fix) == 3 and any("preserved in place" in line for line in fix), settled
        assert "TAIL-NEEDLE" in (e2e_ws / "tests" / "test_app.py").read_text(encoding="utf-8")

        ep_id = str(settled["episode_id"])
        refused = client.call(
            "episode_inspect", {"episode_id": ep_id, "question": "  ", "views": []}
        )
        assert refused["ok"] is False and refused["error"] == "empty_question"

        zoomed = client.call(
            "episode_inspect",
            {
                "episode_id": ep_id,
                "question": "which case failed past the stdout clip",
                "views": [
                    {"kind": "check", "name": "pytest", "offset_lines": 0, "limit_lines": 200}
                ],
            },
        )
        assert zoomed["ok"] is True, zoomed
        assert "TAIL-NEEDLE" in zoomed["views"][0]["text"]

        evolution = e2e_ws / "memory" / "evolution"
        monkeypatch.setenv("EVOLUTION_DIR", str(evolution))
        from evolver.gep.episode_record import load_inspect_calls
        from evolver.ops.meta_report import build_meta_report

        panel = build_meta_report([], inspect_calls=load_inspect_calls())["panel"]["improver_tools"]
        assert panel["episode_inspect_calls"] == 1

    def test_07_auto_hijack_does_not_change_instructions(
        self, client: _McpClient, e2e_ws: Path
    ) -> None:
        hijacked = _McpClient(e2e_ws, extra_env={"EVOLVER_SWARM_AUTO_HIJACK": "1"})
        try:
            normal = client.init_result["result"]["instructions"]
            instructions = hijacked.init_result["result"]["instructions"]
            assert instructions == normal
            assert "EVOLVER SWARM" in instructions
        finally:
            hijacked.close()


# ---------------------------------------------------------------------------
# Tier B — live LLM loop E2E (DeepSeek as the host executor)
# ---------------------------------------------------------------------------


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestLiveLlmLoopE2E:
    def test_live_host_settles_a_round_into_episodes(
        self, client: _McpClient, e2e_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import re

        _commit_python_project(e2e_ws)
        monkeypatch.setenv("GEP_ASSETS_DIR", str(e2e_ws / "gep"))
        monkeypatch.setenv("EVOLUTION_DIR", str(e2e_ws / "memory" / "evolution"))

        system = (
            "You are a Python developer driving the EVOLVER 3-tool FSM loop. "
            "Reply with EXACTLY two fenced blocks:\n"
            "```hypothesis\n"
            "<one plain sentence describing adding multiply(a, b) to src/app.py>\n"
            "```\n"
            "```code\n<new Python function multiply(a: int, b: int) -> int>\n```\n"
        )
        answer = _deepseek_chat(system, "Add multiply(a, b) to src/app.py.")

        def fenced(tag: str) -> str:
            match = re.search(r"```" + tag + r"\s*\n(.*?)```", answer, re.DOTALL)
            assert match, f"LLM reply missing ```{tag} block"
            return match.group(1).strip()

        hyp_line, code_block = fenced("hypothesis"), fenced("code")
        begun = client.call(
            "evolve_begin", {"hypothesis": hyp_line, "target_files": ["src/app.py"]}
        )
        assert begun["ok"] is True

        with (e2e_ws / "src" / "app.py").open("a", encoding="utf-8") as fh:
            fh.write("\n\n" + code_block + "\n")

        settled = client.call("evolve_settle", {"summary": hyp_line})
        assert settled.get("episode_id"), settled
