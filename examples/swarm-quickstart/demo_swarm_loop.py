#!/usr/bin/env python
"""Drive the zero-touch FSM 3-tool evolver MCP loop over a real stdio server.

Walks a disposable repository through the full v1.114.0 host experience:
1. IDLE catalog check (`evolve_begin` + `evolve_status`; `run_lens`/`evolve_settle` hidden)
2. Zero-side-effect preview (`evolve_begin` with empty hypothesis -> `discovery_only=True`)
3. Round 1 (Honest Draft Rejection): lock hypothesis -> incomplete edit -> `evolve_settle`
   returns `ok=False, outcome="draft_preserved"` with a 3-line `actionable_fix` while
   keeping workspace edits intact and positive vault count `+0`
4. Round 2 (Lightning Promotion): re-enter `ACTIVE_RUN` -> run read-only `import_impact`
   and `ast_hotspot` lenses -> fix `calc.py` -> `evolve_settle` passes `< 3s` AST L0
   lightning validation -> `ok=True`, in-band `blackbox`, immutable `episode_id`
5. Read-only audit (`episode_get`, `episode_inspect`, `tool_cycle_timeline`)

Pass `--llm` to ask DeepSeek (`deepseek-v4-flash`) to propose the arithmetic fix
from the GEP dispatch prompt instead of the deterministic local patch.

Usage:
    uv run python examples/swarm-quickstart/demo_swarm_loop.py [--llm] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = Path(__file__).resolve().parent / "skills"

LLM_SYSTEM = """You are the executor of the EVOLVER SWARM loop. Reply with a
single fenced ```python block containing the fixed `calc.py` implementation so
`add(a: int, b: int) -> int` returns `a + b`."""


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}\n{'-' * 60}")


def show(label: str, value: Any, limit: int = 160) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + " …"
    print(f"  {label}: {text}")


class McpClient:
    def __init__(self, ws: Path, state_base: Path) -> None:
        env = dict(os.environ)
        env.update(
            {
                "EVOLVER_REPO_ROOT": str(ws),
                "EVOLVER_STATE_ROOT": str(state_base / "state"),
                "EVOLVER_HOME": str(state_base / "home"),
                "EVOLVER_CONFIG": json.dumps(
                    {
                        "hitl_mode": "off",
                        "load_max": 999.0,
                        "a2a_hub_url": "http://127.0.0.1:9",
                        "skill_roots": str(SKILL_ROOT),
                    }
                ),
            }
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "evolver.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(ws),
            env=env,
        )
        self._id = 0
        self.notifications: list[str] = []
        self.init = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "swarm-demo", "version": "1.114.0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv_response(self, expected_id: int) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            assert line, "server closed the stream"
            frame = json.loads(line)
            if "id" not in frame:
                method = str(frame.get("method") or "")
                if method:
                    self.notifications.append(method)
                continue
            if frame["id"] == expected_id:
                return frame

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        req_id = self._id
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        return self.recv_response(req_id)

    def tool_names(self) -> set[str]:
        res = self.request("tools/list")["result"]
        return {t["name"] for t in res.get("tools", [])}

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        resp = self.request("tools/call", {"name": name, "arguments": args or {}})
        assert "result" in resp, f"MCP error calling {name}: {resp}"
        result = resp["result"]
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


def deepseek_fix_code(dispatch_prompt: str) -> str:
    import httpx

    default_fix = "def add(a: int, b: int) -> int:\n    return a + b\n"
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("  !! DEEPSEEK_API_KEY not set — falling back to deterministic patch")
        return default_fix
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    print(f"  calling {model} …")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": dispatch_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = str(resp.json()["choices"][0]["message"]["content"] or "")
    match = re.search(r"```(?:python)?\s*\n(.*?)```", content, flags=re.DOTALL)
    return (match.group(1).strip() + "\n") if match else default_fix


def seed_workspace(ws: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "demo@t"],
        ["git", "config", "user.name", "demo"],
    ):
        subprocess.run(cmd, cwd=ws, check=True, capture_output=True)
    (ws / "README.md").write_text("# swarm demo workspace\n", encoding="utf-8")
    (ws / "calc.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a - b\n",
        encoding="utf-8",
    )
    (ws / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed micro-bug"],
        cwd=ws,
        check=True,
        capture_output=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="use DeepSeek as the executor")
    parser.add_argument("--keep", action="store_true", help="keep the temp workspace")
    args = parser.parse_args()

    tmp_ctx = None if args.keep else tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    base = Path(tmp_ctx.name if tmp_ctx else tempfile.mkdtemp(prefix="swarm-demo-"))
    ws = base / "ws"
    ws.mkdir(parents=True)
    seed_workspace(ws)

    print(f"workspace: {ws}")
    print(f"executor : {'DeepSeek (deepseek-v4-flash)' if args.llm else 'local deterministic fix'}")

    client = McpClient(ws, base)
    summary: list[tuple[str, str]] = []
    try:
        step(1, "握手与 IDLE 态动态工具面核验（evolve_status）")
        idle_tools = client.tool_names()
        assert "evolve_begin" in idle_tools and "evolve_status" in idle_tools
        assert "run_lens" not in idle_tools and "evolve_settle" not in idle_tools
        status = client.call("evolve_status")
        show("fsm_state", status["fsm_state"])
        show("idle core tools", sorted(idle_tools & {"evolve_begin", "evolve_status"}))
        show("version", status["version"])
        summary.append(("idle_status", f"fsm={status['fsm_state']} v{status['version']}"))

        step(2, "零副作用信号预览（evolve_begin 空假说探测）")
        preview = client.call("evolve_begin", {"agent_name": "demo-host"})
        assert preview["discovery_only"] is True and preview["fsm_state"] == "IDLE"
        show("discovery_only", preview["discovery_only"])
        show("recommended_operators", len(preview.get("recommended_operators") or []))
        summary.append(("preview", f"discovery_only={preview['discovery_only']}"))

        step(3, "第一轮：双轨草稿保留演示（未修复即结算 → draft_preserved + 3 行指引）")
        r1 = client.call(
            "evolve_begin",
            {
                "hypothesis": "Attempt incomplete tweak in calc.py",
                "target_files": ["calc.py"],
                "agent_name": "demo-host",
            },
        )
        assert r1["fsm_state"] == "ACTIVE_RUN"
        # Edit calc.py with an incomplete fix so pytest fails
        (ws / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a * b\n",
            encoding="utf-8",
        )
        s1 = client.call("evolve_settle", {"summary": "Tried multiplication"})
        assert s1["ok"] is False and s1["outcome"] == "draft_preserved"
        assert "a * b" in (ws / "calc.py").read_text(encoding="utf-8")
        show("r1 outcome", f"ok={s1['ok']} outcome={s1['outcome']} (patch preserved in worktree)")
        show("actionable_fix", s1.get("actionable_fix"))
        summary.append(("round_1", f"{s1['outcome']} (3-line fix returned)"))

        step(4, "第二轮：开启周期 + 只读算子透镜诊断（run_lens）")
        r2 = client.call(
            "evolve_begin",
            {
                "hypothesis": "Replace operator in calc.add with + so test_add passes",
                "target_files": ["calc.py"],
                "agent_name": "demo-host",
            },
        )
        active_tools = client.tool_names()
        assert r2["fsm_state"] == "ACTIVE_RUN"
        assert "evolve_begin" not in active_tools
        assert {"run_lens", "evolve_settle", "evolve_status"} <= active_tools
        impact = client.call("run_lens", {"name": "import_impact", "target": "calc.py"})
        hotspot = client.call("run_lens", {"name": "ast_hotspot", "target": "calc.py"})
        assert impact["ok"] is True and impact["read_only"] is True
        show(
            "active core tools",
            sorted(active_tools & {"run_lens", "evolve_settle", "evolve_status"}),
        )
        show("import_impact", impact.get("impacted_tests"))
        show("ast_hotspot", hotspot.get("items"))
        summary.append(("round_2_lens", f"impacted_tests={impact.get('impacted_tests')}"))

        step(5, "执行修复 + <3s L0 闪电验证原子结算（evolve_settle）")
        prompt = str(r2.get("dispatch_prompt") or "")
        fixed_src = (
            deepseek_fix_code(prompt)
            if args.llm
            else "def add(a: int, b: int) -> int:\n    return a + b\n"
        )
        (ws / "calc.py").write_text(fixed_src, encoding="utf-8")
        t0 = time.perf_counter()
        s2 = client.call(
            "evolve_settle",
            {"summary": "Fixed calc.add operator to +", "agent_name": "demo-host"},
        )
        elapsed = time.perf_counter() - t0
        assert s2["ok"] is True, s2
        assert s2["fsm_state"] == "IDLE"
        blackbox = s2.get("blackbox") or {}
        show("r2 outcome", f"ok={s2['ok']} outcome={s2['outcome']} ({elapsed:.2f}s)")
        show("episode_id", s2.get("episode_id"))
        show(
            "blackbox",
            {
                "wall_time_ms": blackbox.get("wall_time_ms"),
                "lenses_run": len(blackbox.get("lens_calls") or []),
                "ast_delta": blackbox.get("ast_delta"),
            },
        )
        show("list_changed notifications", len(client.notifications))
        summary.append(("round_2_settle", f"{s2['outcome']} in {elapsed:.2f}s"))

        step(6, "只读经验回查与时间线核验（episode_get + tool_cycle_timeline）")
        ep = client.call("episode_get", {"episode_id": s2["episode_id"]})
        timeline = client.call("tool_cycle_timeline", {"limit": 5})
        show("episode attribution", ep.get("gates", {}).get("attribution"))
        show("timeline items", len(timeline.get("items") or []))
        summary.append(
            (
                "audit",
                f"episode={s2['episode_id'][:16]}… timeline={len(timeline.get('items') or [])}",
            )
        )
    finally:
        client.close()
        if tmp_ctx:
            time.sleep(0.2)
            tmp_ctx.cleanup()

    print("\n" + "=" * 60)
    print("SWARM LOOP SUMMARY (FSM 3-Tool Protocol)")
    print("=" * 60)
    for name, result in summary:
        print(f"  {name:<16} {result}")
    print(
        "\n下一步：在任意项目运行 `evolver init` 一键接入 — 见 examples/swarm-quickstart/README.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
