#!/usr/bin/env python
"""Drive the full evolver swarm loop over a real stdio MCP server.

Deterministic by default (a local sample plays the executor); pass --llm to
have DeepSeek (deepseek-v4-flash) actually execute the GEP dispatch prompt.
Stdlib-only MCP client — reads tool results from the structuredContent
channel (the spec requires a top-level object, so non-dict returns arrive as
{"result": ...}).

Usage:
    uv run python examples/swarm-quickstart/demo_swarm_loop.py [--llm] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = Path(__file__).resolve().parent / "skills"

SAMPLE_EXECUTOR_RESPONSE = """Executed mutation per the dispatch directive.

Work summary: added the missing import and resolved the module path so the
ImportError no longer reproduces; validation command passes.

Extracted asset:
```json
{
  "type": "Gene",
  "id": "gene_demo_swarm_loop",
  "category": "repair",
  "summary": "Repair ImportError by adding missing imports (demo loop)",
  "signals_match": ["ImportError"],
  "strategy": ["Locate the missing module from the traceback"],
  "preconditions": [],
  "validation": ["python --version"],
  "avoid": []
}
```
"""

LLM_SYSTEM = """You are the executor of the EVOLVER SWARM loop. You receive a
GEP (Genome Evolution Protocol) dispatch prompt; this run is sandboxed, so do
not attempt file edits. Reply with (1) a short work summary, then (2) exactly
ONE fenced ```json block with a single valid Gene object using EXACTLY these
keys: {"type": "Gene", "id": "gene_demo_swarm_loop", "category": "repair",
"summary": "...", "signals_match": ["..."], "strategy": ["..."],
"preconditions": [], "validation": ["python --version"], "avoid": []}."""


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}\n{'-' * 60}")


def show(label: str, value: Any, limit: int = 160) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + " …"
    print(f"  {label}: {text}")


class McpClient:
    def __init__(self, ws: Path) -> None:
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
                "EVOLVER_SKILL_ROOTS": str(SKILL_ROOT),
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
        self.init = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "swarm-demo", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line, "server closed the stream"
        return json.loads(line)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return self.recv()

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": args or {}})["result"]
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


def deepseek_execute(dispatch_prompt: str) -> str:
    import httpx

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("  !! DEEPSEEK_API_KEY not set — falling back to the sample executor")
        return SAMPLE_EXECUTOR_RESPONSE
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
            "temperature": 0.2,
            "max_tokens": 4000,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return str(resp.json()["choices"][0]["message"]["content"] or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="use DeepSeek as the executor")
    parser.add_argument("--keep", action="store_true", help="keep the temp workspace")
    args = parser.parse_args()

    tmp_ctx = None if args.keep else tempfile.TemporaryDirectory()
    ws = Path(tmp_ctx.name if tmp_ctx else tempfile.mkdtemp(prefix="swarm-demo-")) / "ws"
    ws.mkdir(parents=True)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "demo@t"],
        ["git", "config", "user.name", "demo"],
    ):
        subprocess.run(cmd, cwd=ws, check=True, capture_output=True)
    (ws / "README.md").write_text("# swarm demo workspace\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init", "--allow-empty"],
        cwd=ws,
        check=True,
        capture_output=True,
    )
    print(f"workspace: {ws}")
    print(f"executor : {'DeepSeek (deepseek-v4-flash)' if args.llm else 'local sample'}")

    client = McpClient(ws)
    summary: list[tuple[str, str]] = []
    try:
        step(1, "连接与接管（swarm_boot）")
        assert "SWARM EVOLUTION" in client.init["result"]["instructions"]
        show("instructions", "…包含 SWARM EVOLUTION 接管指引 ✓")
        boot = client.call("swarm_boot", {"agent_name": "demo-host"})
        show("protocol", boot["instrument_prompt"][:60])
        summary.append(("boot", boot["next_action"]))

        step(2, "引擎面板（swarm_status）")
        status = client.call("swarm_status")
        show("version", status["version"])
        show("genes/capsules", f"{status['genes']}/{status['capsules']}")
        show("supervision", status["supervision"]["state"])
        summary.append(("status", f"v{status['version']} genes={status['genes']}"))

        step(3, "Hooks 桥：错误输出 → 进化信号（swarm_hook_event）")
        hook = client.call(
            "swarm_hook_event",
            {"event": "signal_detect", "payload": {"content": "ImportError: cannot import name"}},
        )
        show("detected", hook["detected_signals"])
        summary.append(("hook_event", ",".join(hook["detected_signals"]) or "(none)"))

        step(4, "技能生态桥：SKILL.md → 技能基因（swarm_skills）")
        scan = client.call("swarm_skills", {"action": "scan"})
        show("discovered", [s["name"] for s in scan["skills"]])
        synced = client.call("swarm_skills", {"action": "sync"})
        show("installed", [i["id"] for i in synced["installed"]])
        summary.append(("skills", ",".join(i["name"] for i in synced["installed"]) or "(none)"))

        step(5, "进化 tick：产出 GEP 变异提示词（swarm_tick）")
        tick = client.call("swarm_tick", {"agent_name": "demo-host"})
        show("run_id", tick.get("run_id") or "(paused/none)")
        show("dispatch_reason", tick.get("dispatch_reason"))
        prompt = tick.get("dispatch_prompt") or ""
        show("dispatch_prompt", prompt[:120] if prompt else "(no prompt this cycle)")
        summary.append(("tick", str(tick.get("dispatch_reason"))))

        if prompt:
            step(6, "执行变异（executor）")
            response = deepseek_execute(prompt) if args.llm else SAMPLE_EXECUTOR_RESPONSE
            show("executor output", response, limit=220)
            summary.append(("execute", f"{len(response)} chars"))

            step(7, "蒸馏入库（swarm_distill）")
            distilled = client.call("swarm_distill", {"response_text": response})
            show("genes installed", distilled.get("genes"))
            summary.append(("distill", f"genes={distilled.get('genes')}"))

        step(8, "验证门（swarm_solidify）")
        solidified = client.call("swarm_solidify", {})
        show("ok", solidified.get("ok"))
        show("error/gate", solidified.get("error") or "(gate passed)")
        summary.append(("solidify", str(solidified.get("error") or "ran")))

        step(9, "统一评估信号 E（swarm_feedback）")
        feedback = client.call(
            "swarm_feedback",
            {
                "primary_score": 0.85,
                "textual_gradient": "demo loop: mutation applied cleanly",
                "agent_name": "demo-host",
            },
        )
        show("degraded", feedback["degraded"])
        summary.append(("feedback", f"degraded={feedback['degraded']}"))

        step(10, "HOTL 监督：暂停 → tick 拒绝 → 恢复（swarm_supervise）")
        client.call("swarm_supervise", {"action": "pause", "reason": "demo"})
        paused_tick = client.call("swarm_tick", {})
        show("paused tick", f"paused={paused_tick.get('paused')} next={paused_tick['next_action']}")
        client.call("swarm_supervise", {"action": "resume"})
        summary.append(("supervise", "pause→refuse→resume ✓"))
    finally:
        client.close()
        if tmp_ctx:
            time.sleep(0.2)
            tmp_ctx.cleanup()

    print("\n" + "=" * 60)
    print("SWARM LOOP SUMMARY")
    print("=" * 60)
    for name, result in summary:
        print(f"  {name:<12} {result}")
    print("\n下一步：把你的宿主接入蜂群 — 见 examples/swarm-quickstart/README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
