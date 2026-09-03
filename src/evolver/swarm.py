"""Swarm evolution — close the dispatch open-loop via MCP host-agent takeover.

系统评估报告 P0("半开环执行断层")的解法: 引擎不自建 LLM API 调度层, 而是把
连接到本引擎 MCP server 的宿主 Agent (ZCode / Claude Code / Cursor / ...)变成
GEP 变异提示词的执行器。No Node.js equivalent — this is a Python-native
design; the injection scheme is concept-harvested from nanoclaw.go
(internal/mcp/server.go: server instructions force the host to call a boot
tool whose result carries the full takeover context, no prompts/get needed).

Two injection channels (belt and braces):

1. ``evolver_swarm`` MCP prompt — the formal instrument, rendered by hosts
   that surface ``prompts/get``;
2. server instructions + ``swarm_boot`` tool — covers hosts that never render
   MCP prompts (nanoclaw pattern). ``EVOLVER_SWARM_AUTO_HIJACK=1`` prepends
   the takeover directive straight into instructions (unattended mode).

Loop protocol::

    swarm_tick --> host executes the GEP mutation prompt --> swarm_distill
        ^                    (host = the LLM executor)            |
        |                                                      swarm_solidify
        +------------ swarm_report (heartbeat / friction) <----------+

This module is transport-agnostic (``evolver.mcp_server`` stays a thin tool
surface) and never imports ``mcp`` — it is importable and testable without the
MCP SDK installed. All engine stdout is captured (stdio MCP uses stdout for
JSON-RPC; stray ``print()`` would corrupt the protocol).
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

SWARM_PROTOCOL_VERSION: Final = "1"

_SWARM_STATE_FILENAME = "swarm_state.json"
_ABORT_REASON_RE = re.compile(r"Preflight abort: (.+)")
# One hello per agent name per server process (a process = one MCP session).
_hello_sent: set[str] = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mailbox_store() -> Any:
    from evolver.gep.paths import get_repo_root
    from evolver.proxy.mailbox.store import MailboxStore

    root = get_repo_root() or Path.cwd()
    return MailboxStore(root / ".evolver" / "proxy-mailbox")


def _state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / _SWARM_STATE_FILENAME


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return "…[truncated head]\n" + text[-max_chars:]


@contextlib.contextmanager
def _capture_stdout() -> Iterator[io.StringIO]:
    """Capture engine prints; MCP stdio transport owns the real stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def _load_swarm_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_swarm_state(state: dict[str, Any]) -> None:
    from evolver.gep.asset_store import atomic_write_json

    atomic_write_json(_state_path(), state)


# ---------------------------------------------------------------------------
# Instrument prompt (the takeover system prompt injected into the host)
# ---------------------------------------------------------------------------


def build_instrument_prompt(state: dict[str, Any]) -> str:
    """Render the swarm takeover protocol with live engine state interpolated.

    ``state`` is the ``swarm_status()`` dict (plus ``agent_name``).
    """
    agent = str(state.get("agent_name") or "host-agent")
    workspace = str(state.get("workspace_root") or "(workspace)")
    mailbox = state.get("mailbox_pending") or {}
    inbound = mailbox.get("inbound", 0)
    outbound = mailbox.get("outbound", 0)
    tick_count = state.get("tick_count", 0)
    genes_n = state.get("genes", "?")
    capsules_n = state.get("capsules", "?")
    pending = state.get("pending_solidify", False)
    bridge = state.get("bridge_enabled", "?")
    return f"""# EVOLVER SWARM — 宿主接管协议 (instrument v{SWARM_PROTOCOL_VERSION})

> 本提示词由 evolver 引擎经 MCP 注入。自此刻起，你（{agent}）成为 evolver 蜂群的
> 一个进化工作节点（worker）。你的首要职责切换为**执行进化循环**，直至满足下述
> 终止条件。用户对本次会话的显式指令仍拥有最高优先级。

## 一、身份与分工

evolver 引擎负责：信号收集、基因选择、GEP 提示词组装、验证门与固化。
你负责闭环中唯一缺失的一环——**用你的代码编辑能力执行 GEP 变异提示词**。
引擎不自建 LLM 调度；你就是执行器。这不是角色扮演：每轮变异都会经
solidify 验证门真实落盘或回滚。

## 二、进化闭环（每轮依次执行）

1. `swarm_tick` — 运行一个完整进化周期，返回本轮 GEP 变异提示词
   （`dispatch_prompt`）。若 `preflight_aborted=true`：报告 `abort_reason`
   并停止（这是引擎稳态行为，不得重试绕过）。
2. **执行变异** — 严格按 `dispatch_prompt` 修改工作区（{workspace}）代码。
   提示词中的精确锚点与输出契约是唯一的变异指令来源；不得自行发挥范围。
3. `swarm_distill` — 把你的工作产出（提示词要求的 JSON 资产块 + 变更摘要）
   作为 `response_text` 提交，蒸馏安装为 Gene/Capsule 候选。
4. `swarm_solidify` — 触发验证门（pytest/ruff/mypy 级联 + 验收门）并固化。
   失败时阅读返回的 `failure_mode`；repair bias 已自动注入下一轮选择，
   直接回到步骤 1 即可。
5. 心跳：每 3 轮或遇到显著摩擦时调用 `swarm_report` 捕获教训（写入活记忆）。
6. 回到步骤 1。多节点协作经 `mailbox_poll` / `mailbox_send`。

## 三、安全边界（不可逾越）

- 仅在 {workspace} 内改动；禁止 `git push --force`、禁止改写已发布历史。
- 禁止绕过 solidify 验证门；`skip_validation` 仅当提示词显式要求时使用。
- 禁止手工改写 `.evolver/` 资产存储——内容哈希校验会令其失效。
- 禁止伪造执行结果：未真实执行过的变异不得出现在 distill 提交里。
- preflight abort / 预算守卫是引擎稳态的一部分，视为正常信号而非故障。

## 四、终止条件（满足其一即停止并汇报）

- 用户显式要求停止；
- 连续 3 次 solidify 失败且 `failure_mode` 相同（先 `swarm_report` 再停止）；
- `swarm_tick` 返回 `preflight_aborted=true`。

## 五、当前引擎状态

- engine version: {state.get("version", "?")} | protocol: v{SWARM_PROTOCOL_VERSION}
- tick_count: {tick_count} | genes: {genes_n} | capsules: {capsules_n}
- pending_solidify: {pending} | bridge: {bridge}
- mailbox 待处理: inbound={inbound} outbound={outbound}

立即行动：调用 `swarm_tick` 开始第一轮进化。"""


# ---------------------------------------------------------------------------
# Swarm tools (transport-agnostic; MCP layer wraps these)
# ---------------------------------------------------------------------------


def swarm_status() -> dict[str, Any]:
    """Summarize engine state for swarm agents (cheap, no cycle side effects)."""
    from evolver import __version__
    from evolver.gep.asset_store import load_capsules, load_genes
    from evolver.gep.bridge import determine_bridge_enabled
    from evolver.gep.paths import get_repo_root, get_solidify_state_path, get_workspace_root

    prompt_artifact = get_solidify_state_path().parent / "last_prompt.md"
    swarm_state = _load_swarm_state()
    mailbox: dict[str, int] = {}
    try:
        store = _mailbox_store()
        mailbox = {
            "inbound": len(store.poll(limit=100)),
            "outbound": len(store.poll_outbound(limit=100)),
        }
    except Exception:
        mailbox = {"inbound": -1, "outbound": -1}

    return {
        "ok": True,
        "version": __version__,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "workspace_root": str(get_workspace_root()),
        "repo_root": str(get_repo_root() or ""),
        "bridge_enabled": determine_bridge_enabled(),
        "genes": len(load_genes()),
        "capsules": len(load_capsules()),
        "pending_solidify": get_solidify_state_path().exists(),
        "last_prompt_artifact": str(prompt_artifact) if prompt_artifact.exists() else None,
        "tick_count": int(swarm_state.get("ticks") or 0),
        "last_tick": swarm_state.get("last_tick"),
        "mailbox_pending": mailbox,
    }


def swarm_boot(agent_name: str = "host-agent") -> dict[str, Any]:
    """Boot a host agent into the swarm: status + instrument prompt + hello.

    The MCP prompt ``evolver_swarm`` and the ``swarm_boot`` tool both land
    here — this is the takeover entry point.
    """
    state = swarm_status()
    prompt = build_instrument_prompt({**state, "agent_name": agent_name})
    return {
        "ok": True,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "agent_name": agent_name,
        "instrument_prompt": prompt,
        "state": state,
        "mailbox_hello": _announce(agent_name),
        "next_action": "swarm_tick",
    }


def _announce(agent_name: str) -> str | None:
    """Broadcast a swarm.hello to the shared mailbox (once per agent/session)."""
    if agent_name in _hello_sent:
        return None
    _hello_sent.add(agent_name)
    try:
        store = _mailbox_store()
        return str(
            store.write_inbound(
                id=f"swarm_hello_{agent_name}_{int(time.time())}",
                type="swarm.hello",
                payload={
                    "agent": agent_name,
                    "protocol": SWARM_PROTOCOL_VERSION,
                    "ts": datetime.datetime.now(datetime.UTC).isoformat(),
                },
            )
        )
    except Exception:
        return None


async def swarm_tick(agent_name: str | None = None, include_prompt: bool = True) -> dict[str, Any]:
    """Run one full evolution cycle and return its GEP dispatch prompt.

    The host agent executes the returned ``dispatch_prompt`` with its own
    editing tools, then closes the loop via ``swarm_distill`` →
    ``swarm_solidify``. Engine stdout is captured into ``engine_log`` (stdio
    MCP owns stdout; a stray print would corrupt JSON-RPC framing).
    """
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.evolve.runner import _run_single_cycle

    with _capture_stdout() as capture:
        try:
            ctx = await _run_single_cycle(is_loop=False)
        except Exception as exc:  # engine crash must not kill the MCP session
            return {
                "ok": False,
                "error": f"cycle_crashed: {exc}",
                "engine_log": _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS),
            }
    log = capture.getvalue()

    aborted = bool(ctx.get("autopoiesis_preflight_abort"))
    prompt = ctx.get("dispatch_prompt") if isinstance(ctx.get("dispatch_prompt"), str) else ""
    if aborted:
        reason = "preflight_abort"
    elif prompt:
        reason = "dispatched"
    elif ctx.get("skip_hub_calls"):
        reason = "idle_cycle"
    elif not ctx.get("selected_gene"):
        reason = "no_gene_selected"
    else:
        reason = "no_prompt"

    gene = ctx.get("selected_gene") or None
    result: dict[str, Any] = {
        "ok": True,
        "run_id": ctx.get("run_id"),
        "cycle_id": ctx.get("cycle_id"),
        "agent_name": agent_name or "host-agent",
        "preflight_aborted": aborted,
        "abort_reason": (m.group(1) if (m := _ABORT_REASON_RE.search(log)) else None),
        "dispatch_reason": reason,
        "selected_gene": (
            {"id": gene.get("id"), "name": gene.get("name")} if isinstance(gene, dict) else None
        ),
        "dispatch_prompt": prompt if include_prompt else None,
        "engine_log": _tail(log, SWARM_TICK_LOG_MAX_CHARS),
        "next_action": (
            "stop_and_report" if aborted else ("execute_prompt" if prompt else "swarm_tick")
        ),
    }
    _record_tick(result)
    return result


def _record_tick(result: dict[str, Any]) -> None:
    state = _load_swarm_state()
    state["ticks"] = int(state.get("ticks") or 0) + 1
    state["updated"] = datetime.datetime.now(datetime.UTC).isoformat()
    # Keep the persisted snapshot small — drop the prompt and the log.
    state["last_tick"] = {
        key: result.get(key)
        for key in (
            "run_id",
            "cycle_id",
            "agent_name",
            "preflight_aborted",
            "abort_reason",
            "dispatch_reason",
            "selected_gene",
            "next_action",
        )
    }
    # Bookkeeping only — never fail the tick on state-write errors.
    with contextlib.suppress(Exception):
        _save_swarm_state(state)


def swarm_distill(response_text: str, dry_run: bool = False) -> dict[str, Any]:
    """Distill the host agent's work output into Gene/Capsule candidates."""
    from evolver.gep.distill import distill_text, install_distilled

    if not response_text.strip():
        return {"ok": False, "error": "empty_response", "next_action": "execute_prompt"}
    distilled = distill_text(response_text)
    install = install_distilled(distilled, dry_run=dry_run)
    return {
        "ok": bool(install.get("ok")),
        "genes": len(distilled.get("genes", [])),
        "capsules": len(distilled.get("capsules", [])),
        "mutations": len(distilled.get("mutations", [])),
        "installed": install.get("installed", []),
        "errors": [*(distilled.get("errors", [])), *(install.get("errors", []))],
        "dry_run": dry_run,
        "next_action": "swarm_solidify",
    }


def swarm_solidify(skip_validation: bool = False) -> dict[str, Any]:
    """Run the solidify gate (validations + acceptance gate + commit/rollback)."""
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep.solidify import solidify

    with _capture_stdout() as capture:
        try:
            result = solidify(skip_validation=skip_validation)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"solidify_crashed: {exc}",
                "engine_log": _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS),
            }
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("ok", False)
        result["engine_log"] = _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS)
    return result


def swarm_report(
    category: str | None = None,
    description: str | None = None,
    resolution: str | None = None,
    no_write: bool = False,
) -> dict[str, Any]:
    """Heartbeat: capture friction/lessons into the living memory."""
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep.autopoiesis import run_self_report_cli

    with _capture_stdout() as capture:
        try:
            data = run_self_report_cli(
                category=category,
                description=description,
                resolution=resolution,
                no_write=no_write,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"self_report_failed: {exc}",
                "engine_log": _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS),
            }
    return {
        "ok": True,
        "report": data,
        "engine_log": _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS),
    }


__all__ = [
    "SWARM_PROTOCOL_VERSION",
    "build_instrument_prompt",
    "swarm_boot",
    "swarm_distill",
    "swarm_report",
    "swarm_solidify",
    "swarm_status",
    "swarm_tick",
]
