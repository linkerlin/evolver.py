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
from typing import Any, Final, Literal

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
   并停止（这是引擎稳态行为，不得重试绕过）。若 `paused=true`（HOTL
   监督暂停）：立即停止并告知用户，等待 `resume`。若 `supervision_veto`
   非空：本基因已被人类否决，不得执行，直接进入下一轮 tick。
2. **执行变异** — 严格按 `dispatch_prompt` 修改工作区（{workspace}）代码。
   提示词中的精确锚点与输出契约是唯一的变异指令来源；不得自行发挥范围。
3. `swarm_distill` — 把你的工作产出（提示词要求的 JSON 资产块 + 变更摘要）
   作为 `response_text` 提交，蒸馏安装为 Gene/Capsule 候选。
4. `swarm_solidify` — 触发验证门（pytest/ruff/mypy 级联 + 验收门）并固化。
   失败时阅读返回的 `failure_mode`；repair bias 已自动注入下一轮选择，
   直接回到步骤 1 即可。
5. `swarm_feedback` — 每轮执行后诚实上报统一评估信号 E：
   `primary_score`（0-1）、`metrics`（可选多维诊断）、`textual_gradient`
   （自然语言方向——什么有效/什么没用）。低分或失败会自动注入下轮
   repair-bias 信号；评分必须反映真实执行效果。
6. 心跳：每 3 轮或遇到显著摩擦时调用 `swarm_report` 捕获教训（写入活记忆）。
7. 回到步骤 1。多节点协作经 `mailbox_poll` / `mailbox_send`。

## 三、Hooks 集成（信号自动采集）

- 若宿主支持 hooks（ZCode / Claude Code / Cursor / Codex / Kiro / OpenCode）：
  建议用户执行 `evolver setup-hooks --platform <platform> --project-dir {workspace}`
  （或调用 `swarm_hooks` 工具 `action=install`，可先 `action=status` 预览）——
  session 边界与工具输出中的错误信号将自动采集进进化记忆。
- 若宿主未装或不支持文件 hooks：会话开始与结束时、以及捕获到错误输出时，
  调用 `swarm_hook_event`（`event=session_start/session_end/signal_detect`，
  `payload` 携带 `content` 文本）——检测到的信号（如 `log_error`、
  `perf_bottleneck`）直接注入下一周期的基因选择。

## 四、安全边界（不可逾越）

- 仅在 {workspace} 内改动；禁止 `git push --force`、禁止改写已发布历史。
- 禁止绕过 solidify 验证门；`skip_validation` 仅当提示词显式要求时使用，
  且需过 HITL 审批门——`EVOLVER_HITL_MODE=on` 时须人类批准
  （`evolver hitl approve` 或经你转达人类决定），超时未决自动拒绝
  （fail-safe）；同一 run 被拒后不得重试申请。
- 人在环上（HOTL）监督不可规避：`paused` 状态不得启动新周期；
  `supervision_veto` 命中的基因/操作不得执行；`supervision:directive:`
  信号是人类转向指令，视为最高优先级上下文。用户经 `swarm_supervise`
  （pause/resume/veto/direct）或 CLI `evolver supervise` 行使监督权。
- 禁止手工改写 `.evolver/` 资产存储——内容哈希校验会令其失效。
- 禁止伪造执行结果：未真实执行过的变异不得出现在 distill 提交里，
  `swarm_feedback` 的评分亦不得虚报。
- preflight abort / 预算守卫是引擎稳态的一部分，视为正常信号而非故障。

## 五、终止条件（满足其一即停止并汇报）

- 用户显式要求停止；
- 连续 3 次 solidify 失败且 `failure_mode` 相同（先 `swarm_report` 再停止）；
- `swarm_tick` 返回 `preflight_aborted=true`。

## 六、当前引擎状态

- engine version: {state.get("version", "?")} | protocol: v{SWARM_PROTOCOL_VERSION}
- tick_count: {tick_count} | genes: {genes_n} | capsules: {capsules_n}
- pending_solidify: {pending} | bridge: {bridge}
- mailbox 待处理: inbound={inbound} outbound={outbound}

立即行动：调用 `swarm_tick` 开始第一轮进化。"""


# ---------------------------------------------------------------------------
# Swarm tools (transport-agnostic; MCP layer wraps these)
# ---------------------------------------------------------------------------


def _feedback_stability(rows: list[dict[str, Any]], window: int = 10) -> dict[str, Any] | None:
    """EvoX dual-convergence observation surface: score stddev (<0.01 counts as
    converged) over the last ``window`` feedback reports. Observation only —
    enforcement stays with the signal-history modulation (plateau detection)."""
    scores = [
        float(r["primary_score"]) for r in rows if isinstance(r.get("primary_score"), int | float)
    ][-window:]
    if len(scores) < 3:
        return None
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stddev = variance**0.5
    return {
        "n": len(scores),
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "converged": stddev < 0.01,
    }


def swarm_status() -> dict[str, Any]:
    """Summarize engine state for swarm agents (cheap, no cycle side effects)."""
    from evolver import __version__
    from evolver.gep.asset_store import load_capsules, load_genes
    from evolver.gep.bridge import determine_bridge_enabled
    from evolver.gep.feedback import load_recent_feedback
    from evolver.gep.hitl import hitl_mode_enabled, list_pending
    from evolver.gep.paths import get_repo_root, get_solidify_state_path, get_workspace_root
    from evolver.gep.supervision import supervision_summary

    prompt_artifact = get_solidify_state_path().parent / "last_prompt.md"
    swarm_state = _load_swarm_state()
    recent_feedback = load_recent_feedback(10)
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
        "feedback": {
            "recent_count": len(recent_feedback),
            "last": recent_feedback[-1] if recent_feedback else None,
            "stability": _feedback_stability(recent_feedback),
        },
        "hitl": {
            "mode": "on" if hitl_mode_enabled() else "off",
            "pending": len(list_pending()),
        },
        "supervision": supervision_summary(),
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

    HOTL supervision (v1.101.0): the tripwire runs first (consecutive
    degraded feedback may auto-pause), a paused state refuses the cycle, and
    a supervisor veto on the selected gene withholds the dispatch prompt.
    """
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.evolve.runner import _run_single_cycle
    from evolver.gep import supervision

    tripwire = supervision.auto_pause_check()
    if supervision.is_paused():
        summary = supervision.supervision_summary()
        return {
            "ok": True,
            "paused": True,
            "supervision": summary,
            "tripwire": tripwire,
            "agent_name": agent_name or "host-agent",
            "next_action": "await_supervisor_resume",
        }

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
    gene = ctx.get("selected_gene") or None

    veto: dict[str, Any] | None = None
    if prompt and isinstance(gene, dict):
        veto = supervision.check_veto(str(gene.get("id") or ""), str(gene.get("name") or ""))
        if veto is not None:
            prompt = ""  # withhold: the supervisor vetoed this gene

    if veto is not None:
        reason = "supervision_veto"
    elif aborted:
        reason = "preflight_abort"
    elif prompt:
        reason = "dispatched"
    elif ctx.get("skip_hub_calls"):
        reason = "idle_cycle"
    elif not ctx.get("selected_gene"):
        reason = "no_gene_selected"
    else:
        reason = "no_prompt"

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
        "supervision_veto": veto,
        "dispatch_prompt": (prompt or None) if include_prompt else None,
        "engine_log": _tail(log, SWARM_TICK_LOG_MAX_CHARS),
        "next_action": (
            "stop_and_report" if aborted else ("swarm_tick" if not prompt else "execute_prompt")
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


def _pending_solidify_run_id() -> str:
    """Best-effort run_id of the pending solidify state (gates HITL subjects)."""
    import json as _json

    from evolver.gep.paths import get_solidify_state_path

    try:
        data = _json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        return str((data.get("last_run") or {}).get("run_id") or "unknown")
    except Exception:
        return "unknown"


def swarm_solidify(skip_validation: bool = False, agent_name: str = "host-agent") -> dict[str, Any]:
    """Run the solidify gate (validations + acceptance gate + commit/rollback).

    High-risk calls (``skip_validation=True``) pass through the HITL approval
    gate first (EvoX concept harvest): ``EVOLVER_HITL_MODE=on`` blocks until a
    human approves / fail-safe rejects on timeout; mode ``off`` auto-approves
    but journals the decision for audit.
    """
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep import hitl, supervision
    from evolver.gep.solidify import solidify

    run_id = _pending_solidify_run_id()
    veto = supervision.check_veto(f"solidify:{run_id}", run_id)
    if veto is not None:
        return {
            "ok": False,
            "error": "supervision_veto",
            "veto": veto,
            "next_action": "swarm_tick",
        }

    approval: dict[str, Any] | None = None
    if skip_validation:
        subject = f"solidify_skip_validation:{run_id}"
        approval = hitl.request_approval(
            subject=subject,
            risk_reason="swarm_solidify with skip_validation=True bypasses the validation cascade",
            requested_by=agent_name,
        )
        if approval.get("status") != "approved":
            return {
                "ok": False,
                "error": f"hitl_{approval.get('status', 'pending')}",
                "approval": approval,
                "next_action": (
                    "await_human_approval" if approval.get("status") == "pending" else "swarm_tick"
                ),
            }

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
        if approval is not None:
            result["hitl_approval"] = approval
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


def swarm_feedback(
    primary_score: float,
    textual_gradient: str = "",
    metrics: dict[str, float] | None = None,
    success: bool = True,
    error_message: str | None = None,
    eval_mode: Literal["train", "validation", "test"] = "validation",
    sample_count: int = 0,
    agent_name: str = "host-agent",
    run_id: str | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Report a unified evaluation signal E (EvoX concept harvest) into the loop.

    Degraded reports (low ``primary_score`` or ``success=false``) inject
    repair-bias signals for the next cycle; the natural-language
    ``textual_gradient`` rides along as a direction hint.
    """
    from evolver.gep.feedback import EvaluationFeedback, record_feedback

    try:
        fb = EvaluationFeedback(
            primary_score=primary_score,
            textual_gradient=textual_gradient,
            metrics=metrics or {},
            success=success,
            error_message=error_message,
            eval_mode=eval_mode,
            sample_count=sample_count,
            agent_name=agent_name,
            run_id=run_id,
            cycle_id=cycle_id,
        )
    except Exception as exc:
        return {"ok": False, "error": f"invalid_feedback: {exc}"}
    return record_feedback(fb)


def swarm_supervise(
    action: Literal["status", "pause", "resume", "direct", "veto", "unveto"],
    text: str | None = None,
    pattern: str | None = None,
    veto_id: str | None = None,
    reason: str = "",
    by: str = "human",
) -> dict[str, Any]:
    """HOTL supervision entry point (human-on-the-loop; v1.101.0).

    ``pause``/``resume`` flip the loop state (tick refuses cycles while
    paused); ``direct`` injects a steering signal into the next cycle;
    ``veto``/``unveto`` manage substring patterns that block ticked genes and
    solidify subjects; ``status`` returns the summary.
    """
    from evolver.gep import supervision

    if action == "status":
        return {"ok": True, "supervision": supervision.supervision_summary()}
    if action == "pause":
        result = supervision.set_state(True, by=by, reason=reason)
        return {**result, "supervision": supervision.supervision_summary()}
    if action == "resume":
        result = supervision.set_state(False, by=by)
        return {**result, "supervision": supervision.supervision_summary()}
    if action == "direct":
        return supervision.add_directive(text or "", by=by)
    if action == "veto":
        return supervision.add_veto(pattern or "", by=by)
    if action == "unveto":
        return supervision.remove_veto(veto_id or "")
    return {"ok": False, "error": f"unknown_action:{action}"}


_HOOK_EVENTS: Final = ("session_start", "session_end", "signal_detect")


def swarm_hook_event(
    event: str,
    payload: dict[str, Any] | None = None,
    source: str = "host-agent",
) -> dict[str, Any]:
    """In-process hook bridge for MCP-only hosts (no file hooks needed).

    Mirrors the adapter runtime scripts (adapters/scripts/signal_detect.py):
    the payload's content is run through the shared signal detector, and
    detected tags go straight into ``pending_signals`` — the same channel
    autopoiesis friction and feedback gradients use — so the next cycle's
    selection sees them. Hosts with file hooks installed do not need this;
    the scripts already feed memory collection.
    """
    import contextlib
    import datetime as _dt

    from evolver.adapters.scripts.signal_detect import _extract_content, detect_signals
    from evolver.gep.asset_store import append_pending_signals
    from evolver.gep.paths import get_evolution_dir

    if event not in _HOOK_EVENTS:
        return {
            "ok": False,
            "error": f"unknown_event:{event}",
            "supported": list(_HOOK_EVENTS),
        }
    content, file_path = _extract_content(payload or {})
    signals = detect_signals(content)
    if signals:
        append_pending_signals(signals)
    entry = {
        "event": event,
        "source": source,
        "signals": signals,
        "file_path": file_path or None,
        "at": _dt.datetime.now(_dt.UTC).isoformat(),
    }
    with contextlib.suppress(OSError):
        journal = get_evolution_dir() / "hook_events.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "event": event,
        "source": source,
        "detected_signals": signals,
        "injected": signals,
        "file_path": file_path or None,
        "note": "" if signals else "no signals detected — nothing injected",
    }


def swarm_hooks(
    action: Literal["status", "install", "uninstall"] = "status",
    platform: str = "auto",
    project_dir: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Manage IDE/agent hooks from the swarm surface.

    Thin wrapper over ``adapters.setup_hooks.install_hooks`` so a host agent
    can bootstrap its own file hooks over MCP (``status`` previews via
    dry-run). Platforms: cursor / claude-code / codex / kiro / opencode /
    vscode / generic / auto.
    """
    from evolver.adapters.hook_adapter import detect_platform
    from evolver.adapters.setup_hooks import install_hooks
    from evolver.gep.paths import get_workspace_root

    target = project_dir or str(get_workspace_root())
    if action == "status":
        result = install_hooks(platform=platform, project_dir=target, dry_run=True)
        return {
            "ok": bool(result.get("ok", True)),
            "action": "status",
            "detected_platform": detect_platform(target),
            "requested_platform": platform,
            "project_dir": target,
            "preview": result.get("messages", []),
        }
    if action == "install":
        result = install_hooks(platform=platform, project_dir=target, force=force, dry_run=dry_run)
        return {**result, "action": "install"}
    if action == "uninstall":
        result = install_hooks(
            platform=platform, project_dir=target, uninstall=True, dry_run=dry_run
        )
        return {**result, "action": "uninstall"}
    return {"ok": False, "error": f"unknown_action:{action}"}


__all__ = [
    "SWARM_PROTOCOL_VERSION",
    "build_instrument_prompt",
    "swarm_boot",
    "swarm_distill",
    "swarm_feedback",
    "swarm_hook_event",
    "swarm_hooks",
    "swarm_report",
    "swarm_solidify",
    "swarm_status",
    "swarm_supervise",
    "swarm_tick",
]
