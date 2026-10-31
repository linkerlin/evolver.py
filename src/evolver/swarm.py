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
2. a short standing server instruction plus the ``swarm_boot`` tool — covers
   hosts that never render MCP prompts (nanoclaw pattern). The standing text
   starts the loop when the user message has no other task, the bench gate can
   publish, and supervision is not paused; otherwise boot returns a handoff.
   The full protocol is
   the tool result, not the instruction. ``EVOLVER_SWARM_AUTO_HIJACK=1`` does
   not change that text: it forces the HITL gate on and refuses host-relayed
   approvals.

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
import os
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
    from evolver.gep.paths import get_mailbox_dir
    from evolver.proxy.mailbox.store import MailboxStore

    return MailboxStore(get_mailbox_dir())


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
    tick_count = state.get("tick_count", 0)
    genes_n = state.get("genes", "?")
    capsules_n = state.get("capsules", "?")
    pending = state.get("pending_solidify", False)
    # Pending run first: a tick writes fresh solidify state and would clobber
    # the un-solidified run (tool-check 2026-09-05: boot said pending_solidify:
    # True while directing the host to tick first).
    next_action, first_action = _opening_action(state)
    # Chores wait while a run is unsaved. Skills are not in this list: syncing
    # the user skill roots on boot flooded the gene pool.
    boot_once = _boot_once(bool(pending))
    boot_note = (
        "待固化时列表为空：先固化。完成后再补一次 `swarm_hook_event`（event=session_start）。"
        if pending
        else "做完再执行立即行动。不要在开机时同步技能。"
    )
    supervision_raw = state.get("supervision") or {}
    supervision_state = (
        supervision_raw.get("state", "?") if isinstance(supervision_raw, dict) else "?"
    )
    bench_raw = state.get("bench_pack_gate") or {}
    armed = bool(bench_raw.get("armed", False)) if isinstance(bench_raw, dict) else False
    raw_ids = bench_raw.get("train_ids") if isinstance(bench_raw, dict) else None
    if isinstance(raw_ids, list) and raw_ids:
        shown = [str(item) for item in raw_ids[:20]]
        train_ids_text = ", ".join(shown)
        hidden = len(raw_ids) - len(shown)
        if hidden:
            train_ids_text += f" (+{hidden} more, {len(raw_ids)} total)"
    else:
        train_ids_text = "(none — pack not loaded)"
    boot_once_json = json.dumps(boot_once, ensure_ascii=False)
    hotl = gate_handoff_skipped()
    gate_handoff = "hotl" if hotl else "human"
    hotl_note = (
        "\n当前 `gate_handoff: hotl`：人已选择不在 tick 前等待。"
        if hotl
        else ""
    )
    soft_gate_note = (
        "\n门未就绪（pack_absent / no_baseline）、或分数未改进（drop/flat/regression）时默认 "
        "**soft-continue**：仍可 `swarm_tick` / `swarm_solidify`；Accept/publish 走 "
        "soft-accept（带 warnings + next_steps），**不**伪造 Parent baseline，**不**在候选对话中"
        "打开 val 密封材料。建议仍按 `evolver doctor` / `evolver bench baseline` "
        "补齐，但非强制。只有 secrets / val_seal 违规仍硬拒绝。"
    )
    hitl = state.get("hitl") or {}
    hitl_mode = hitl.get("mode", "?")
    hitl_pending = hitl.get("pending", 0)
    fence_open = "```json"
    fence_close = "```"
    from evolver.gep.prompt import EVOLVER_CHARTER

    working = state.get("working_session") if isinstance(state.get("working_session"), dict) else {}
    preview = str((working or {}).get("preview") or "").strip()
    working_block = (
        "\n## WORKING_SESSION.md（当轮草稿，线索层，不进验收）\n" + preview + "\n"
        if preview
        else ""
    )
    prompt = f"""# EVOLVER SWARM — 宿主接管协议 (instrument v{SWARM_PROTOCOL_VERSION})

> 本提示词由 evolver 引擎经 MCP 注入。你（{agent}）是进化工作节点：
> 引擎选择、验证、固化；你只改代码。本条消息里的用户指令优先。
> 本条没有别的任务时，先按下面开机。开机后用一句话说明实际状态：循环开始
> （含 soft-continue / 有建议缺口）、硬门禁需人处理、或已经暂停。说「停」即可停下。

## 宪章

{EVOLVER_CHARTER}

## 开机（本会话一次）

按 `swarm_boot` 返回的 `boot_once` 逐项调用。它们自己的 `next_action` 忽略。
本轮列表：{boot_once_json}
{boot_note}
若 `state.mailbox_pending.inbound` 大于 0：接着 `tool_mailbox_poll`，处理完
`tool_mailbox_ack`。`supervision: state=paused` 时不要 tick。用户说「停」才 pause，
说「继续」才 resume，见终止条件。不要自己 resume。

立即行动（`next_action={next_action}`）：{first_action}

## 循环（每轮一步，只服从返回里的 `next_action`）

1. `swarm_tick` — 看 `dispatch_prompt`。提示词携带 **Evidence Pack**。
   它标着 **PROPOSAL REQUIRED**，或返回 `proposal_required=true` 时，
   本轮改动**必须**经 `swarm_propose` 提交，不得自由编辑；自由编辑仅限新颖信号与结构性
   改动。`paused=true`、`preflight_aborted=true`、`supervision_veto` 非空、
   `next_action=stop_and_report`（含 `error=instance_lock_held`）都停下来报告。
2. 编辑 — 只改 `dispatch_prompt` 锚点所写的范围。工作区是 {workspace}。
3. `swarm_distill` — `response_text` 里要有下面这种围栏。
   `genes + capsules + mutations` 为 0 时按返回的 `hint` 重交，不重做编辑。
   EvolutionEvent 与 PersonalityState 会被静默丢弃。
{fence_open}
{{"type": "Gene", "id": "gene_<slug>", "category": "repair",
 "summary": "...", "signals_match": ["..."], "strategy": ["..."]}}
{fence_close}
   `category` 只能是 repair、optimize、innovate、explore。
4. `swarm_hypothesis` — 固化之前调用，五个字段都要有，看返回 `ok=true`。
   `swarm_propose` 与 `swarm_solidify` 也可以带 `hypothesis` 参数。引擎不代写。
{fence_open}
{{"hypothesis": "一句话说明改了什么", "dimension": "content",
 "mechanism_family": "与本轮同类的上次改法",
 "target_hook": "改动的文件或函数",
 "mechanism_check": [{{"id": "<train 题 id>",
 "before": "改前如何失败", "after": "改后如何通过"}}]}}
{fence_close}
   `dimension` 只能是 content、tool、schema。`id` 从下方 `train_ids` 里挑，
   禁止编造，禁止引用 val。要有 before 与 after。
   可选 `expected_outcome`：`{{"expected_checks_to_pass": ["pytest"]}}`，写你预计
   会通过的检查命令片段。结算时引擎对照实际检查写 `prediction_delta`，不影响门。
5. `swarm_solidify` — 看 `ok`。失败读 `failure_mode.retryable`：
   true 回到步骤 1；false 停止并报告。
6. `swarm_feedback` — `primary_score` 用第 5 步返回的 `score`，没有就填 0。
   `textual_gradient` 写一句实际发生了什么。
7. 回到步骤 1。每 3 轮或卡住时调用 `swarm_report`。

## 终止条件

- 用户说「停」或要求停止：调用 `swarm_supervise`，`action=pause`，然后停止。不要让用户自己敲命令。
  用户之后说「继续」：调用 `swarm_supervise`，`action=resume`，再重新 `swarm_boot`。
  返回 `error=host_relay_blocked` 时，请用户执行 `evolver supervise resume`。
- `next_action=stop_and_report`，或 `paused=true`，或 `preflight_aborted=true`，
  或 `error=instance_lock_held`；
- `next_action=await_human_approval`：停。`swarm_approvals` 把待决读给人，
  人决定后才 `swarm_approval_resolve`。返回 `error=host_relay_blocked` 时请人执行
  `evolver hitl approve` 或 `evolver hitl reject`。不要自己批准。
- 连续 3 次 `failure_mode.reasonClass` 相同：先 `swarm_report` 再停。

`retryable=true` 的拒绝是稳态，回到步骤 1。

## 不要做（安全边界）

- 只在 {workspace} 内改动。禁止 `git push --force`，禁止改写已发布历史。
- 不手改 `.evolver/`。内容哈希校验会令其失效。
- 不在本对话解 val。题面回到写下候选的这场对话，密封就失效；求解在另一上下文
  完成，评分只读已经写好的沙箱。沙箱不全即是 `unmeasured`，门拒绝，基线不动。
- 不改 `EVOLVER_SWARM_GATE_HANDOFF` 或 MCP 配置。是否跳过人由人决定。
- 不调用 `skip_validation`。那要过 HITL：`EVOLVER_HITL_MODE=on` 时须人类批准，
  超时未决自动拒绝。若仍返回 `await_human_approval`，按终止条件转达，不重试。
- 不虚报 `swarm_feedback` 的分数，也不把没执行过的变异写进 distill。
- `paused` 时不启动新周期。`supervision_veto` 命中的基因不得执行。
  `supervision:directive:` 是人类转向，视为最高优先级上下文。

## 功能（宿主自己调用）

- 看到报错或失败输出：`swarm_hook_event`，`event=signal_detect`，`payload.content` 贴原文。
  会话结束再调 `event=session_end`。
- 有文件 Hooks 的宿主：`swarm_hooks`，先 `action=status`。用户在本条消息里同意再 `install`。
  没装过也不阻塞循环。
- 用户说的是一套多步修复或创新，而不是一轮基因：`swarm_workflow_run`，`template` 用
  `repair-cycle` 或 `innovate-cycle`。按返回的 `awaiting_agent` 做完，用 `swarm_workflow_act` 交回。
  要回看全状态用 `swarm_workflow_status`。
- 要按关键词找基因：`tool_asset_search`。要全文再 `tool_asset_get`。
- 要按 id 读上一轮：`episode_get`。`dispatch_prompt` 里已有摘要时不必再读。
- 摘要写了 truncated：`episode_inspect`，必须带 `question`，按 `views` 看未截断现场。
- 返回 `next_action=call_swarm_checkpoint_working`：先 `swarm_checkpoint_working` 把假设、
  已排除路径和 episode id 写入 WORKING_SESSION.md，再压缩或开新会话。
- 要看状态、不跑周期：`swarm_status`。资源 `evolver://status` 是同一份。
- 要看最近周期：`tool_cycle_timeline`，或资源 `evolver://events/recent`。
  投影陈旧时再 `tool_rebuild_views`。
- 多节点：`tool_mailbox_poll` / `tool_mailbox_send`。
- 不要在开机时调用 `swarm_skills`。用户明确要求把技能纳入进化时才 `action=sync`。

## 交给人 / soft-continue

冻结 val 包门仍是外部适应度标尺；首次准备缺口不再硬卡住循环，带 warnings + next_steps 继续：

- `bench_pack.reason=pack_absent`：**可继续**。建议人按
  `examples/swarm-quickstart/README.md`「开箱 / 首次准备」执行
  `evolver setup` / `evolver doctor --fix` / `evolver bench freeze`。
  soft-accept 可发布但会警告；装包仍强烈推荐。
- `reason=no_baseline`：**可继续**。建议在另一上下文写好 val 沙箱后执行
  `evolver bench baseline`（或 doctor --fix 在沙箱齐时测量）。基线不由候选
  书写；本对话不得解 val、不得打开 val 密封材料。soft-accept **不**写入 Parent bar。
- `reason=unmeasured`：**可 soft-accept**。把 `pending_tasks` 报告给人；val 由
  另一上下文写入 `sandboxes/r1` 与 `sandboxes/r2`。非强制完成后再 solidify。
- `reason=drop / flat / regression`：**可 soft-accept**。分数未改进可继续迭代，
  soft-accept 带 warnings；只是不写入 Parent baseline。
- `ok=true` 且 `bench_pack.accept=true`（含 soft_accept）：停并报告。发布要人执行
  `evolver session accept`（soft 时 CLI 会打印 warnings）。没有配对会话时，
  这次返回就是最终结果。
- **仍硬拒绝**：val_seal_breach（密封材料泄漏）、secrets（保护路径改写）。
{hotl_note}{soft_gate_note}
{working_block}
## 当前状态

- pending_solidify: {pending}
- bench_pack_gate.armed: {armed}
- gate_handoff: {gate_handoff}
- train_ids: {train_ids_text}
- supervision: state={supervision_state}
- hitl: mode={hitl_mode} pending={hitl_pending}
- tick_count: {tick_count} | genes: {genes_n} | capsules: {capsules_n}
"""
    return prompt


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


def _code_staleness() -> dict[str, Any] | None:
    """Compare process start against the newest source mtime (status surface).

    Dogfood round-6: a reconnect landing between two fixes produced a
    half-new process; the host only found out by diffing prompt texts.
    The stdio server loads code at spawn — surface the mismatch so the
    host sees "reload required" directly.
    """
    try:
        import os

        import psutil

        pkg_dir = Path(__file__).resolve().parent
        newest_src = max(p.stat().st_mtime for p in pkg_dir.rglob("*.py"))
        proc_start = psutil.Process(os.getpid()).create_time()
        return {
            "stale": newest_src > proc_start,
            "process_started_at": proc_start,
            "newest_src_mtime": newest_src,
        }
    except Exception:
        return None


def _package_source_root() -> Path | None:
    """Best-effort git root of the running evolver package source tree."""
    pkg_dir = Path(__file__).resolve().parent
    # Editable checkout: …/src/evolver → repo root is parents[1].
    candidates = [pkg_dir.parents[1], pkg_dir.parents[2], pkg_dir.parent, pkg_dir]
    for root in candidates:
        if (root / ".git").exists():
            return root
    for parent in pkg_dir.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _source_revision() -> str | None:
    """Git SHA of the running package/source checkout, if available."""
    import subprocess

    root = _package_source_root()
    if root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    sha = (result.stdout or "").strip()
    return sha or None


def _stale_import_error(exc: ImportError) -> dict[str, Any]:
    """Self-diagnosing error for stale long-lived MCP hosts (round-17).

    A process that predates a code change holds old modules in memory while
    lazily importing new ones from disk; the mixed import chain dies with a
    raw ``ImportError`` (round-16 live: tick/distill crashed on
    ``ANCHOR_PROBE_TIMEOUT_S``). Convert it into an actionable result instead
    of a stack trace: fail closed, tell the host to reconnect.
    """
    return {
        "ok": False,
        "error": "code_stale_process",
        "reason": str(exc)[:300],
        "next_action": "reconnect_host",
        "hint": (
            "this MCP process predates the current src tree (in-memory old "
            "modules + on-disk new ones); restart/reconnect the host so a "
            "fresh process loads matching code (see swarm_status "
            "code_staleness)"
        ),
    }


def _pending_solidify_state() -> bool:
    """True when the state file holds a last_run newer than the last solidify.

    The file persists after success by design (lineage: ``last_run`` +
    ``last_solidify``), so existence alone kept reporting pending forever —
    and boot's pending-first directive then sent every fresh host into a
    full no-op cascade (round-9 measurement: 424 s, ok:True, nothing landed).
    """
    from evolver.gep.paths import get_solidify_state_path

    path = get_solidify_state_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True  # unreadable state: assume pending (fail toward solidify)
    last_run_id = str((data.get("last_run") or {}).get("run_id") or "")
    last_done_id = str((data.get("last_solidify") or {}).get("run_id") or "")
    return bool(last_run_id) and last_run_id != last_done_id


def _bench_gate_snapshot() -> dict[str, Any]:
    """Frozen bench-pack gate state for status/boot/instrument (never raises —
    an unusable gate is ``armed: false``, not a crash)."""
    try:
        from evolver.bench.frozen_gate import gate_snapshot

        return gate_snapshot()
    except Exception:
        return {"armed": False}


def _build_state_health(
    *,
    workspace_id: str,
    state_root: Path,
    bench_gate: dict[str, Any],
    legacy_info: dict[str, Any],
) -> dict[str, Any]:
    """U-10: Single-pane health view of evolution, hypothesis, gep, and bench baseline."""
    from evolver.gep.hypothesis import hypothesis_path
    from evolver.gep.paths import get_evolution_dir, get_gep_assets_dir

    evo_dir = get_evolution_dir().resolve()
    hyp_file = Path(hypothesis_path()).resolve()
    gep_dir = get_gep_assets_dir().resolve()
    state_root_res = state_root.resolve()

    def _under_state_root(p: Path) -> bool:
        try:
            p.relative_to(state_root_res)
            return True
        except ValueError:
            return False

    evo_aligned = _under_state_root(evo_dir) or bool(os.environ.get("EVOLUTION_DIR"))
    hyp_aligned = (hyp_file.parent == evo_dir) and (
        _under_state_root(hyp_file) or bool(os.environ.get("EVOLUTION_DIR"))
    )
    gep_aligned = _under_state_root(gep_dir) or bool(os.environ.get("GEP_ASSETS_DIR"))
    baseline_armed = bool(bench_gate.get("armed")) and (bench_gate.get("baseline") is not None)

    return {
        "workspace_id": workspace_id,
        "state_root": str(state_root_res),
        "all_aligned": bool(evo_aligned and hyp_aligned and gep_aligned),
        "evolution": {
            "path": str(evo_dir),
            "exists": evo_dir.is_dir(),
            "workspace_id": workspace_id,
            "aligned": evo_aligned,
        },
        "hypothesis": {
            "path": str(hyp_file),
            "exists": hyp_file.is_file(),
            "workspace_id": workspace_id,
            "aligned": hyp_aligned,
        },
        "gep": {
            "path": str(gep_dir),
            "exists": gep_dir.is_dir(),
            "workspace_id": workspace_id,
            "aligned": gep_aligned,
        },
        "bench_baseline": {
            "armed": bool(bench_gate.get("armed")),
            "baseline_present": bench_gate.get("baseline") is not None,
            "digest_bound": bool(bench_gate.get("digest")),
            "score": bench_gate.get("baseline"),
            "ready": baseline_armed,
        },
        "legacy_in_repo": legacy_info,
    }


def swarm_status() -> dict[str, Any]:
    """Summarize engine state for swarm agents (cheap, no cycle side effects)."""
    from evolver import __version__
    from evolver.gep.adaptive import feedback_mutation_bias
    from evolver.gep.asset_store import load_capsules, load_genes
    from evolver.gep.bridge import determine_bridge_enabled
    from evolver.gep.feedback import load_recent_feedback
    from evolver.gep.hitl import hitl_mode_enabled, list_pending
    from evolver.gep.paths import (
        compute_workspace_id,
        detect_legacy_in_repo_state,
        discover_git_candidates,
        get_repo_root,
        get_solidify_state_path,
        get_workspace_root,
        get_workspace_state_dir,
    )
    from evolver.gep.supervision import supervision_summary

    ws_root = get_workspace_root()
    repo_root = get_repo_root(_quiet=True)
    target_root = repo_root or ws_root
    ws_id = compute_workspace_id(target_root)
    state_root = get_workspace_state_dir(target_root)
    legacy_info = detect_legacy_in_repo_state(target_root, warn=True)
    bench_gate = _bench_gate_snapshot()

    mismatch: str | None = None
    git_candidates: list[str] = []
    if repo_root is None:
        git_candidates = discover_git_candidates(ws_root)
        mismatch = f"no_git_repo_at_workspace:{ws_root}" + (
            f" (candidates: {git_candidates})" if git_candidates else ""
        )
    elif repo_root.resolve() != ws_root.resolve():
        mismatch = f"workspace_root ({ws_root}) != repo_root ({repo_root})"

    prompt_artifact = get_solidify_state_path().parent / "last_prompt.md"
    swarm_state = _load_swarm_state()
    recent_feedback = load_recent_feedback(10)
    mailbox: dict[str, int] = {}
    try:
        store = _mailbox_store()
        # "Pending" means status=pending: poll() returns every inbound message
        # (acked/synced included), and counting them all made the label lie —
        # the number only ever went up, even after acks (dogfood round-7).
        inbound_pending = [
            m for m in store.poll(limit=100) if getattr(m, "status", "") == "pending"
        ]
        mailbox = {
            "inbound": len(inbound_pending),
            "outbound": len(store.poll_outbound(limit=100)),
            "unacked_hello": sum(
                1
                for m in inbound_pending
                if getattr(m, "type", "") == "swarm.hello"
            ),
        }
    except Exception:
        mailbox = {"inbound": -1, "outbound": -1}

    return {
        "ok": True,
        "version": __version__,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "workspace_root": str(ws_root),
        "repo_root": str(repo_root or ""),
        "workspace_id": ws_id,
        "state_root": str(state_root),
        "mismatch": mismatch,
        "git_candidates": git_candidates,
        "state_health": _build_state_health(
            workspace_id=ws_id,
            state_root=state_root,
            bench_gate=bench_gate,
            legacy_info=legacy_info,
        ),
        "bridge_enabled": determine_bridge_enabled(),
        "genes": len(load_genes()),
        "capsules": len(load_capsules()),
        "pending_solidify": _pending_solidify_state(),
        "last_prompt_artifact": str(prompt_artifact) if prompt_artifact.exists() else None,
        "source_revision": _source_revision(),
        "code_staleness": _code_staleness(),
        "tick_count": int(swarm_state.get("ticks") or 0),
        "last_tick": swarm_state.get("last_tick"),
        "feedback": {
            "recent_count": len(recent_feedback),
            "last": recent_feedback[-1] if recent_feedback else None,
            "stability": _feedback_stability(recent_feedback),
            "mutation_bias": feedback_mutation_bias(recent_feedback),
        },
        "hitl": {
            "mode": "on" if hitl_mode_enabled() else "off",
            "pending": len(list_pending()),
        },
        "supervision": supervision_summary(),
        "bench_pack_gate": bench_gate,
        "mailbox_pending": mailbox,
        "working_session": _working_snapshot(),
    }


def _working_snapshot() -> dict[str, Any]:
    """Scratch-pad preview plus whether a compact checkpoint is waiting."""
    try:
        from evolver.gep.compact_gate import checkpoint_pending
        from evolver.gep.working_memory import read_working

        text = read_working()
        return {
            "present": bool(text.strip()),
            "chars": len(text),
            "preview": text[:400],
            "compact_checkpoint_pending": checkpoint_pending(),
        }
    except Exception:
        return {
            "present": False,
            "chars": 0,
            "preview": "",
            "compact_checkpoint_pending": False,
        }


def _checkpoint_block() -> dict[str, Any] | None:
    from evolver.gep.compact_gate import pending_block

    block = pending_block()
    if block is None:
        return None
    refused = dict(block)
    refused["working_session"] = _working_snapshot()
    return refused


def _settled_run_barrier(run_id: str) -> dict[str, Any] | None:
    """Return the recorded episode when this run is already landed.

    A run that is still pending (a failed solidify the host may retry) is
    left open. Sealing those would trap boot on ``solidify first`` forever.
    """
    if not run_id or run_id == "unknown" or _pending_solidify_state():
        return None
    from evolver.gep import episode_record

    try:
        ep_id = episode_record.find_episode_id_for_run(run_id)
    except Exception:
        return None
    if not ep_id:
        return None
    return {
        "ok": True,
        "status": "already_settled",
        "run_id": run_id,
        "episode_id": ep_id,
        "episode": {"ok": True, "reason": "already_stored", "id": ep_id},
        "next_action": "swarm_tick",
        "steer_message": (
            "This run_id is already settled. The recorded episode id is returned; "
            "call swarm_tick for a new cycle instead of solidifying again."
        ),
    }


def _gate_gap(gate: Any) -> str | None:
    """Why the frozen gate cannot publish yet, or ``None`` when it can."""
    if not isinstance(gate, dict) or not gate.get("armed"):
        return "pack_absent"
    if gate.get("baseline") is None:
        return "no_baseline"
    return None


def gate_handoff_skipped() -> bool:
    """True when the human chose HOTL over the pre-tick gate handoff."""
    from evolver.config import SWARM_GATE_HANDOFF

    return SWARM_GATE_HANDOFF.strip().lower() == "hotl"


def _opening_action(state: dict[str, Any]) -> tuple[str, str]:
    """What the host does after boot, as ``(next_action, prose)``.

    A pending run is settled first. A paused loop is next, matching the
    ``await_supervisor_resume`` tick returns when already paused. Usability
    gaps (no pack / no Parent baseline) soft-continue into ``swarm_tick`` with
    warnings — they no longer hard-stop on ``await_human``. Drop/flat/seal
    stay hard at solidify time.
    """
    if state.get("pending_solidify"):
        return (
            "swarm_solidify",
            "存在待固化 run——先调用 `swarm_solidify` 完成固化，再回到步骤 1",
        )
    supervision = state.get("supervision")
    if isinstance(supervision, dict) and supervision.get("state") == "paused":
        return (
            "await_supervisor_resume",
            "监督已暂停——不要 tick。告诉用户说「继续」即可恢复。"
            "用户说了才调用 `swarm_supervise` action=resume，不要自己 resume。",
        )
    gap = _gate_gap(state.get("bench_pack_gate"))
    if gap is not None:
        hotl = "（gate_handoff=hotl）" if gate_handoff_skipped() else ""
        return (
            "swarm_tick",
            f"门未就绪（{gap}）{hotl}——soft-continue：调用 `swarm_tick` 开始。"
            "Accept/publish 将带 soft-accept 警告与 next_steps；建议 "
            "`evolver doctor` / `evolver bench baseline`，非强制。"
            "本对话不得解 val、不得打开 val 密封材料。",
        )
    return ("swarm_tick", "调用 `swarm_tick` 开始第一轮进化")


def _boot_once(pending_solidify: bool) -> list[dict[str, Any]]:
    """Tools the host runs once per session, before the evolution step.

    Empty while a run is waiting to solidify. Skill sync is not here: it
    pulls every user skill root into the gene store.
    """
    if pending_solidify:
        return []
    return [{"tool": "swarm_hook_event", "arguments": {"event": "session_start"}}]


def swarm_boot(
    agent_name: str = "host-agent",
    project: str | Path | None = None,
) -> dict[str, Any]:
    """Boot a host agent into the swarm: status + instrument prompt + hello.

    The MCP prompt ``evolver_swarm`` and the ``swarm_boot`` tool both land
    here — this is the takeover entry point. ``next_action`` mirrors the
    instrument prompt's first-action branch (round-57: it was unconditionally
    ``swarm_tick`` while the prompt said "solidify first" when pending —
    hosts reading the structured field got the wrong first action; the
    round-4 fix only covered the prose).
    """
    from evolver.gep.paths import ensure_workspace_meta

    if project is not None and str(project).strip():
        resolved_proj = Path(str(project).strip()).expanduser().resolve()
        os.environ["EVOLVER_REPO_ROOT"] = str(resolved_proj)
        os.environ["OPENCLAW_WORKSPACE"] = str(resolved_proj)
    with contextlib.suppress(Exception):
        ensure_workspace_meta()

    state = swarm_status()
    prompt = build_instrument_prompt({**state, "agent_name": agent_name})
    payload: dict[str, Any] = {
        "ok": True,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "agent_name": agent_name,
        "repo_root": state.get("repo_root"),
        "workspace_id": state.get("workspace_id"),
        "state_root": state.get("state_root"),
        "instrument_prompt": prompt,
        "state": state,
        "mailbox_hello": _announce(agent_name),
        "boot_once": _boot_once(bool(state.get("pending_solidify"))),
        "next_action": _opening_action(state)[0],
    }
    from evolver.gep.working_memory import read_working

    try:
        working_text = read_working()
    except Exception:  # a broken scratch file must not block takeover
        working_text = ""
    if working_text.strip():
        payload["working_session_text"] = working_text
        payload["working_session_source"] = "host_working"
    blocked = _checkpoint_block()
    if blocked is not None:
        payload["next_action"] = blocked["next_action"]
        payload["checkpoint"] = blocked
        payload["steer_message"] = blocked["steer_message"]
    gap = _gate_gap(state.get("bench_pack_gate"))
    if gap is not None and str(payload.get("next_action") or "") != "await_supervisor_resume":
        from evolver.ops.open_box import apply_soft_gap

        payload = apply_soft_gap(payload, gap)
    elif str(payload.get("next_action") or "") == "await_human":
        from evolver.ops.open_box import attach_next_steps

        payload = attach_next_steps(
            {
                **payload,
                "error": gap or "no_baseline",
                "reason": gap,
                "severity": "hard",
            },
            error=gap or "no_baseline",
        )
        payload.setdefault("severity", "hard")
    payload["source_revision"] = state.get("source_revision")
    payload["mailbox_hello_ack"] = _ack_own_hello(agent_name)
    return payload


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


def _ack_own_hello(agent_name: str) -> dict[str, Any]:
    """Auto-ack this agent's pending inbound ``swarm.hello`` mailbox messages.

    Prefer auto-ack over documenting that hosts must call ``mailbox_ack`` for
    their own hello. Matching is by ``payload.agent == agent_name``.
    """
    try:
        store = _mailbox_store()
        pending = [
            m
            for m in store.poll(limit=100, type="swarm.hello")
            if getattr(m, "status", "") == "pending"
            and str((getattr(m, "payload", None) or {}).get("agent") or "") == agent_name
        ]
        ids = [str(m.id) for m in pending]
        acked = int(store.ack(ids)) if ids else 0
        return {"acked": acked, "ids": ids, "agent_name": agent_name}
    except Exception as exc:
        return {"acked": 0, "ids": [], "agent_name": agent_name, "error": str(exc)[:200]}


async def swarm_tick(agent_name: str | None = None, include_prompt: bool = True) -> dict[str, Any]:
    """Run one full evolution cycle and return its GEP dispatch prompt.

    The host agent executes the returned ``dispatch_prompt`` with its own
    editing tools, then closes the loop via ``swarm_distill`` →
    ``swarm_solidify``. Engine stdout is captured into ``engine_log`` (stdio
    MCP owns stdout; a stray print would corrupt JSON-RPC framing).

    HOTL supervision (v1.101.0): the tripwire runs first (consecutive
    degraded feedback may auto-pause), a paused state refuses the cycle, and
    a supervisor veto on the selected gene withholds the dispatch prompt.
    A gate usability gap (no pack / no baseline) soft-continues the cycle with
    warnings + next_steps instead of hard-stopping on ``await_human``.
    """
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS

    try:
        from evolver.evolve.runner import _run_single_cycle
        from evolver.gep import supervision
        from evolver.gep.instance_lock import instance_lock_ctx
    except ImportError as exc:
        # Stale long-lived host: in-memory modules predate the on-disk tree.
        return _stale_import_error(exc)

    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked

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

    gap = _gate_gap(_bench_gate_snapshot())

    with instance_lock_ctx(blocking=False, timeout=0) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "instance_lock_held",
                "agent_name": agent_name or "host-agent",
                "next_action": "stop_and_report",
            }
        result = await _swarm_tick_locked(
            agent_name=agent_name,
            include_prompt=include_prompt,
            tripwire=tripwire,
            run_cycle=_run_single_cycle,
            log_budget=SWARM_TICK_LOG_MAX_CHARS,
            supervision=supervision,
        )
        if gap is not None and isinstance(result, dict):
            from evolver.ops.open_box import SOFT_GAP_ERRORS, apply_soft_gap

            # Preserve a real hard error from the cycle; only soft-label the gap.
            hard_error = result.get("error")
            if hard_error in SOFT_GAP_ERRORS:
                hard_error = None
                result = {**result}
                result.pop("error", None)
            result = apply_soft_gap(result, gap)
            if hard_error:
                result["error"] = hard_error
                result["severity"] = "hard"
            else:
                note = (
                    f"soft-continue ({gap}): tick ran despite missing pack/baseline; "
                    "Accept/publish may soft-accept with warnings. Recommended: "
                    "`evolver doctor` / `evolver bench baseline` (do not open sealed val)."
                )
                warnings = list(result.get("warnings") or [])
                if note not in warnings:
                    warnings.append(note)
                result["warnings"] = warnings
        return result


def _build_tick_checklist(
    *,
    run_id: str | None,
    selected_gene: dict[str, Any] | None,
    proposal_required: bool,
) -> dict[str, Any]:
    """U-13: Structured checklist guiding edit -> distill -> hypothesis -> solidify -> feedback."""
    from evolver.gep.paths import get_repo_root, get_workspace_root, get_workspace_state_dir

    repo = get_repo_root(_quiet=True) or get_workspace_root()
    state_root = get_workspace_state_dir(repo)
    gene_id = (selected_gene or {}).get("id") or "gene_selected"
    return {
        "run_id": run_id,
        "repo_root": str(repo),
        "state_root": str(state_root),
        "steps": [
            {
                "step": 1,
                "phase": "edit",
                "title": "修改代码（仅限 git 工作区）",
                "where_to_edit": str(repo),
                "do_not_touch": ["memory/", ".evolver/", str(state_root)],
                "tool": "swarm_propose" if proposal_required else "file_edit_or_swarm_propose",
            },
            {
                "step": 2,
                "phase": "distill",
                "title": "蒸馏本轮改动与经验线索",
                "tool": "swarm_distill",
                "note": "传入包含 Gene/Capsule 代码块与分析说明的完整响应文本。",
            },
            {
                "step": 3,
                "phase": "hypothesis",
                "title": "声明本轮唯一主假说（未通过 solidify 不会丢失）",
                "tool": "swarm_hypothesis",
                "template": {
                    "hypothesis": f"Applying {gene_id} resolves the target failure mechanism",
                    "dimension": "content",
                    "mechanism_family": "repair",
                    "target_hook": "src/",
                    "mechanism_check": [
                        {
                            "id": "train-task-id",
                            "before": "observed failure or baseline behavior before edit",
                            "after": "observed fix or replay verification after edit",
                        }
                    ],
                },
            },
            {
                "step": 4,
                "phase": "solidify",
                "title": "运行固化门禁（支持分层验证与失败 stash 恢复）",
                "tool": "swarm_solidify",
                "preconditions": [
                    "git status 含有效代码改动",
                    "hypothesis.json 已在 state_root 下就绪",
                    (
                        "可选 validation_scope='related' 传入 argv list"
                        "（如 [['pytest', 'tests/test_x.py']]）"
                    ),
                    (
                        "若失败补丁自动 stash，可通过 restore_stash=True 或 "
                        "`evolver solidify --restore-stash` 恢复"
                    ),
                ],
            },
            {
                "step": 5,
                "phase": "feedback",
                "title": "提交评估反馈闭环",
                "tool": "swarm_feedback",
                "template": {
                    "primary_score": 1.0,
                    "textual_gradient": "What improved and what remains for the next cycle",
                },
            },
        ],
    }


def _format_tick_checklist_footer(checklist: dict[str, Any]) -> str:
    """U-13: Render a concise markdown footer appended to ``dispatch_prompt``."""
    repo = checklist.get("repo_root", "")
    state_root = checklist.get("state_root", "")
    tmpl = json.dumps(checklist["steps"][2]["template"], ensure_ascii=False)
    lines = [
        "",
        "---",
        "## Host Execution Checklist (U-13)",
        (
            f"1. **改哪里 (Edit)**: 仅在仓库根目录 `{repo}` 修改源码/测试"
            f"（严禁写 `memory/` 或 `{state_root}`）。"
        ),
        (
            "2. **蒸馏 (Distill)**: 调用 `swarm_distill(response_text=...)` "
            "提取 Gene/Capsule 并记录宿主线索。"
        ),
        (
            f"3. **假说 (Hypothesis)**: 调用 `swarm_hypothesis(hypothesis={tmpl})`"
            "（若固化失败，假说将自动保留无需重登）。"
        ),
        (
            "4. **固化 (Solidify)**: 调用 `swarm_solidify(validation_scope='related'|'cascade')`；"
            "若被拒，补丁自动保存至 stash，可用 `restore_stash=True` 或 "
            "`evolver solidify --restore-stash` 一键恢复。"
        ),
        (
            "5. **反馈 (Feedback)**: 调用 "
            "`swarm_feedback(primary_score=..., textual_gradient=...)` 完成闭环。"
        ),
    ]
    return "\n".join(lines)


async def _swarm_tick_locked(
    *,
    agent_name: str | None,
    include_prompt: bool,
    tripwire: dict[str, Any],
    run_cycle: Any,
    log_budget: int,
    supervision: Any,
) -> dict[str, Any]:
    with _capture_stdout() as capture:
        try:
            ctx = await run_cycle(is_loop=False)
        except ImportError as exc:  # stale-host lazy import (round-17)
            return _stale_import_error(exc)
        except Exception as exc:  # engine crash must not kill the MCP session
            return {
                "ok": False,
                "error": f"cycle_crashed: {exc}",
                "engine_log": _tail(capture.getvalue(), log_budget),
            }
    log = capture.getvalue()

    if ctx.get("supervision_paused"):
        return {
            "ok": True,
            "paused": True,
            "supervision": supervision.supervision_summary(),
            "tripwire": tripwire,
            "agent_name": agent_name or "host-agent",
            "next_action": "await_supervisor_resume",
        }

    aborted = bool(ctx.get("autopoiesis_preflight_abort"))
    prompt = ctx.get("dispatch_prompt") if isinstance(ctx.get("dispatch_prompt"), str) else ""
    gene = ctx.get("selected_gene") or None

    # Charter step 1 (round-79): the evidence pack's repeat-failure mandate,
    # surfaced structurally so the host doesn't have to parse the prompt
    # block to know this family must go through swarm_propose.
    pack_ctx = ctx.get("evidence_pack")
    mandate = pack_ctx.get("mandate") if isinstance(pack_ctx, dict) else None
    proposal_required = bool(isinstance(mandate, dict) and mandate.get("required"))

    veto: dict[str, Any] | None = (
        ctx.get("supervision_veto") if isinstance(ctx.get("supervision_veto"), dict) else None
    )
    if veto is not None:
        prompt = ""
        if "BUILT_PROMPT" in log:
            log = log.split("BUILT_PROMPT", 1)[0] + "[dispatch withheld]\n"

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

    selected_gene_info = (
        {"id": gene.get("id"), "name": gene.get("name")} if isinstance(gene, dict) else None
    )
    checklist = _build_tick_checklist(
        run_id=ctx.get("run_id"),
        selected_gene=selected_gene_info,
        proposal_required=proposal_required,
    )
    full_prompt = f"{prompt.rstrip()}\n{_format_tick_checklist_footer(checklist)}" if prompt else ""

    result: dict[str, Any] = {
        "ok": True,
        "run_id": ctx.get("run_id"),
        "cycle_id": ctx.get("cycle_id"),
        "agent_name": agent_name or "host-agent",
        "preflight_aborted": aborted,
        "abort_reason": (m.group(1) if (m := _ABORT_REASON_RE.search(log)) else None),
        "dispatch_reason": reason,
        "selected_gene": selected_gene_info,
        "supervision_veto": veto,
        "proposal_required": proposal_required,
        "dispatch_prompt": (full_prompt or None) if include_prompt else None,
        "checklist": checklist,
        "engine_log": _tail(log, log_budget),
        "next_action": (
            "stop_and_report" if aborted else ("swarm_tick" if not prompt else "execute_prompt")
        ),
        "tripwire": tripwire,
        "working_session": _working_snapshot(),
    }
    if aborted or reason == "preflight_abort":
        from evolver.ops.open_box import attach_next_steps

        abort_reason = str(result.get("abort_reason") or "preflight_abort")
        err = "user_lock" if "user lock" in abort_reason.lower() else "preflight_abort"
        result = attach_next_steps({**result, "error": err}, error=err)

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
            "proposal_required",
            "next_action",
        )
    }
    # Round-71: preserve the runner's phase timings across the summary
    # rewrite — _record_cycle_phase_timings writes them BEFORE this tick's
    # bookkeeping; the full-dict load/save above carries them forward, and
    # a regression test pins that (the timing instrument must survive the
    # tick path that runs it).
    # Bookkeeping only — never fail the tick on state-write errors.
    with contextlib.suppress(Exception):
        _save_swarm_state(state)


def swarm_distill(
    response_text: str,
    dry_run: bool = False,
    *,
    strict_transferable: bool = False,
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Distill the host agent's work output into Gene/Capsule candidates.

    Dogfood round-4: a response that yields zero assets used to return silently
    (genes=0, errors=[]) — the host had no way to self-correct the format. The
    result now carries a ``hint`` with the expected asset-block shape so one
    round-trip fixes the submission.
    """
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    try:
        from evolver.gep.distill import DISTILL_FORMAT_HINT, distill_text, install_distilled
    except ImportError as exc:
        return _stale_import_error(exc)

    if not response_text.strip():
        return {"ok": False, "error": "empty_response", "next_action": "execute_prompt"}
    distilled = distill_text(response_text)
    try:
        install = install_distilled(
            distilled,
            dry_run=dry_run,
            attribution=attribution,
            strict_transferable=strict_transferable,
        )
    except ImportError as exc:
        # Deep lazy imports (solidify.record_landed_gene_ids) hit the same
        # stale-host module mix (round-16 live crash).
        return _stale_import_error(exc)
    extracted = (
        len(distilled.get("genes", []))
        + len(distilled.get("capsules", []))
        + len(distilled.get("mutations", []))
    )
    result: dict[str, Any] = {
        "ok": bool(install.get("ok")),
        "genes": len(distilled.get("genes", [])),
        "capsules": len(distilled.get("capsules", [])),
        "mutations": len(distilled.get("mutations", [])),
        "installed": install.get("installed", []),
        "errors": [*(distilled.get("errors", [])), *(install.get("errors", []))],
        "dry_run": dry_run,
        "next_action": "swarm_solidify",
    }
    skipped_genes = install.get("skipped_genes")
    if isinstance(skipped_genes, list) and skipped_genes:
        result["skipped_genes"] = skipped_genes
        if any(
            isinstance(item, dict)
            and str(item.get("reason") or "") == "confounded_or_ineligible_attribution"
            for item in skipped_genes
        ):
            result["skipped_confounded"] = True
    if extracted == 0:
        result["hint"] = DISTILL_FORMAT_HINT
        result["next_action"] = "resubmit_with_asset_blocks"
    elif not dry_run:
        gene_ids = [str(g.get("id")) for g in distilled.get("genes") or [] if g.get("id")]
        if gene_ids:
            from evolver.gep.solidify import record_landed_gene_ids

            record_landed_gene_ids(gene_ids)
    # Round-61 bridge: a GeneProposal embedded in the response text (fenced
    # json block with action/edits) is surfaced as a replay candidate so the
    # host's structural work product reaches the S29/population channel's
    # upstream without a second manual step. Observation-only — nothing is
    # applied here; the proposal still goes through swarm_propose/solidify
    # gates if the operator chooses to replay it.
    proposals = _extract_proposal_candidates(response_text)
    if proposals:
        result["proposal_candidates"] = proposals
        result["proposal_next_step"] = (
            f"{len(proposals)} GeneProposal block(s) detected — replayable via "
            "swarm_propose or `evolver solidify --proposal/--population` "
            "(same validation gates as any mutation)"
        )
    # 经验即证据 §5.2: the host's own account is a clue, not evidence — stored
    # apart from the episode record, tagged with its source. Not in dry_run:
    # a clue for a round that never happened is worse than no clue.
    if not dry_run:
        account = _extract_host_account(response_text)
        if account:
            from evolver.gep import episode_clue

            result["clue"] = episode_clue.append_clue(account, source="host_distill")
    return result


def _extract_host_account(response_text: str) -> str:
    """The host's free-text account: the response minus its fenced asset blocks.

    The distill channel keeps the structured assets; the prose around them is
    the host's own account of what it did and saw — exactly the material the
    engine never observed. Bounded so one verbose host cannot flood the layer.
    """
    prose = re.sub(r"```[a-zA-Z]*\s*\n.*?```", "", response_text, flags=re.DOTALL)
    return prose.strip()[:2000]


def _extract_proposal_candidates(response_text: str) -> list[dict[str, Any]]:
    """Fenced ```json blocks that parse as GeneProposal (action + edits).

    Best-effort: invalid shapes are skipped silently (the distill assets are
    the primary product; the bridge must never turn a format variation into
    an error for the host).
    """
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"```json\s*\n(.*?)```", response_text, re.DOTALL):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if (
            isinstance(data, dict)
            and data.get("action") in ("patch", "create", "no_action")
            and isinstance(data.get("edits"), list)
        ):
            candidates.append(data)
    return candidates


def _pending_solidify_meta() -> dict[str, str]:
    """Pending solidify run_id / gene ids (empty strings if none)."""
    import json as _json

    from evolver.gep.paths import get_solidify_state_path

    try:
        data = _json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        last = data.get("last_run") or {}
        landed = last.get("landed_gene_ids") or []
        head = str(landed[0]) if isinstance(landed, list) and landed else ""
        return {
            "run_id": str(last.get("run_id") or (last.get("mutation") or {}).get("id") or ""),
            "gene_id": str(last.get("selected_gene_id") or ""),
            "landed_gene_id": head,
        }
    except Exception:
        return {"run_id": "", "gene_id": "", "landed_gene_id": ""}


def _pending_solidify_run_id() -> str:
    """Best-effort run_id of the pending solidify state (gates HITL subjects)."""
    return _pending_solidify_meta()["run_id"] or "unknown"


def _hypothesis_payload(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Stamp the pending run id onto a host-supplied hypothesis."""
    stored = dict(payload)
    if run_id and run_id != "unknown":
        stored.setdefault("run_id", run_id)
    return stored


def _record_host_hypothesis(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist the host's hypothesis (演进方案.md §5.3).

    Soft failure by contract: a malformed record is a host fixable error, not
    an engine crash. The host learns the shape here, before paying for a round.
    Recording never passes the gate - the gate re-reads what landed on disk.
    """
    from evolver.gep import hypothesis as hypothesis_mod

    try:
        path = hypothesis_mod.record_hypothesis(payload)
    except hypothesis_mod.HypothesisError as exc:
        return {
            "ok": False,
            "error": "hypothesis_rejected",
            "message": str(exc),
            "failure_mode": {
                "mode": "soft",
                "reasonClass": "hypothesis_rejected",
                "retryable": True,
            },
            "next_action": "swarm_tick",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "hypothesis_unwritable",
            "message": str(exc),
            "failure_mode": {
                "mode": "soft",
                "reasonClass": "hypothesis_unwritable",
                "retryable": True,
            },
            "next_action": "swarm_tick",
        }
    return {"ok": True, "hypothesis_path": str(path), "next_action": "swarm_solidify"}


def swarm_hypothesis(hypothesis: dict[str, Any], agent_name: str = "host-agent") -> dict[str, Any]:
    """Declare this Candidate's one primary hypothesis (演进方案.md §5.3).

    The host owns the hypothesis: only the executor knows what it intends to
    change, so the engine never invents one on its behalf. Fields are
    ``hypothesis`` / ``dimension`` (content|tool|schema) / ``mechanism_family``
    / ``target_hook`` / ``mechanism_check`` (train refs only - the validation
    reserve is sealed).

    Declaring is not passing: the gate re-reads the record and can still refuse.
    """
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    if not isinstance(hypothesis, dict):
        return {
            "ok": False,
            "error": "hypothesis_rejected",
            "message": "hypothesis must be a JSON object",
            "failure_mode": {
                "mode": "soft",
                "reasonClass": "hypothesis_rejected",
                "retryable": True,
            },
            "next_action": "swarm_tick",
        }
    result = _record_host_hypothesis(
        _hypothesis_payload(hypothesis, _pending_solidify_meta()["run_id"])
    )
    if result.get("ok"):
        result["agent_name"] = agent_name
    return result


def swarm_propose(
    proposal: dict[str, Any],
    agent_name: str = "host-agent",
    hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a GeneProposal mechanically with anchor validation.

    S29 mechanical mutation application: validate-all-first, exact unique anchor
    matching, fail-safe against hallucinations.

    ``hypothesis`` (§5.3) is recorded *before* the proposal is applied: the
    claim about what changes must exist before the change itself.

    Takes the same non-blocking instance lock as tick/solidify: a running
    daemon loop owns the workspace while it holds the lock, and a host
    proposal landing mid-cycle would interleave two writers.
    """
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    from evolver.gep.instance_lock import instance_lock_ctx
    from evolver.gep.paths import get_workspace_root

    with instance_lock_ctx(blocking=False, timeout=0) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "instance_lock_held",
                "agent_name": agent_name,
                "next_action": "stop_and_report",
            }
        return _swarm_propose_locked(
            proposal,
            agent_name=agent_name,
            hypothesis=hypothesis,
            workspace_root=get_workspace_root(),
        )


def _swarm_propose_locked(
    proposal: dict[str, Any],
    *,
    agent_name: str,
    hypothesis: dict[str, Any] | None,
    workspace_root: Path,
) -> dict[str, Any]:
    """Body of :func:`swarm_propose` once the instance lock is held."""
    from evolver.gep.proposal import apply_proposal, compose_proposals, parse_proposal

    if hypothesis is not None:
        recorded = _record_host_hypothesis(
            _hypothesis_payload(hypothesis, _pending_solidify_meta()["run_id"])
        )
        if not recorded.get("ok"):
            return recorded

    composition_ledger: list[dict[str, Any]] | None = None
    decision: str | None = None
    try:
        if isinstance(proposal, dict) and isinstance(proposal.get("candidates"), list):
            composed = compose_proposals(
                proposal["candidates"],
                root=workspace_root,
                apply=True,
                gene_id=str(proposal.get("gene_id") or "") or None,
            )
            decision = str(composed.get("decision") or "keep_base")
            composition_ledger = list(composed.get("composition_ledger") or [])
            comp_prop = composed.get("proposal")
            if isinstance(comp_prop, dict):
                action_name = str(comp_prop.get("action") or "no_action")
                gene_id_val = comp_prop.get("gene_id")
            else:
                action_name = str(getattr(comp_prop, "action", None) or "no_action")
                gene_id_val = getattr(comp_prop, "gene_id", None)
            apply_rep = composed.get("apply_report")
            files_changed = (
                list(apply_rep.get("files_changed") or []) if isinstance(apply_rep, dict) else []
            )
        else:
            parsed = parse_proposal(proposal)
            report = apply_proposal(parsed, workspace_root)
            action_name = parsed.action
            gene_id_val = parsed.gene_id
            files_changed = list(report.get("files_changed", []))
    except Exception as exc:
        return {
            "ok": False,
            "error": "proposal_rejected",
            "message": str(exc),
            "next_action": "swarm_tick",
        }

    integrity_report: dict[str, Any] | None = None
    if isinstance(proposal, dict) and proposal.get("check_component_integrity") and files_changed:
        from evolver.gep.policy_check import validate_harness_component_integrity

        raw_integrity = validate_harness_component_integrity(workspace_root, files_changed)
        integrity_report = {
            "ok": bool(raw_integrity.get("ok")),
            "violations": [
                v.to_dict() if hasattr(v, "to_dict") else v
                for v in (raw_integrity.get("violations") or [])
            ],
        }

    # Track pending proposal in swarm state
    state = _load_swarm_state()
    state["last_proposal"] = {
        "action": action_name,
        "gene_id": gene_id_val,
        "files_changed": files_changed,
        "agent_name": agent_name,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }
    _save_swarm_state(state)

    out: dict[str, Any] = {
        "ok": True,
        "action": action_name,
        "gene_id": gene_id_val,
        "files_changed": files_changed,
        "next_action": "swarm_tick" if decision == "keep_base" else "swarm_solidify",
    }
    if decision is not None:
        out["decision"] = decision
    if composition_ledger is not None:
        out["composition_ledger"] = composition_ledger
    if integrity_report is not None:
        out["component_integrity"] = integrity_report
    return out


def swarm_solidify(
    skip_validation: bool = False,
    agent_name: str = "host-agent",
    proposal: dict[str, Any] | None = None,
    hypothesis: dict[str, Any] | None = None,
    *,
    validation_scope: str | None = None,
    related_commands: list[list[str]] | None = None,
    restore_stash: bool = False,
) -> dict[str, Any]:
    """Run the solidify gate (validations + acceptance gate + commit/rollback).

    High-risk calls (``skip_validation=True``) require a pending run and pass
    the HITL gate inside ``solidify()``. ``EVOLVER_HITL_MODE=on`` (or auto-hijack)
    blocks until a human approves; timeout fails safe to reject.
    Optionally accepts a ``proposal`` to mechanically apply before gating (S29).
    ``hypothesis`` (§5.3) is recorded before gating; the host that declines to
    state a claim is refused by the gate rather than measured anyway.

    Takes the same non-blocking instance lock as tick: a running daemon loop
    owns the workspace while it holds the lock, and a host solidify landing
    mid-cycle (stash/rollback) would interleave two writers.
    """
    from evolver.gep.instance_lock import instance_lock_ctx

    with instance_lock_ctx(blocking=False, timeout=0) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "instance_lock_held",
                "agent_name": agent_name,
                "next_action": "stop_and_report",
            }
        return _swarm_solidify_locked(
            skip_validation=skip_validation,
            proposal=proposal,
            hypothesis=hypothesis,
            validation_scope=validation_scope,
            related_commands=related_commands,
            restore_stash=restore_stash,
        )


def _swarm_solidify_locked(
    *,
    skip_validation: bool,
    proposal: dict[str, Any] | None,
    hypothesis: dict[str, Any] | None,
    validation_scope: str | None = None,
    related_commands: list[list[str]] | None = None,
    restore_stash: bool = False,
) -> dict[str, Any]:
    """Body of :func:`swarm_solidify` once the instance lock is held."""
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep import supervision
    from evolver.gep.solidify import solidify

    if restore_stash:
        return solidify(restore_stash=True)

    meta = _pending_solidify_meta()
    run_id = meta["run_id"]
    settled = _settled_run_barrier(str(run_id or ""))
    if settled is not None:
        return settled
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked

    if hypothesis is not None:
        recorded = _record_host_hypothesis(_hypothesis_payload(hypothesis, run_id))
        if not recorded.get("ok"):
            return recorded

    if skip_validation and (not run_id or run_id == "unknown"):
        return {
            "ok": False,
            "error": "skip_validation_requires_pending_run",
            "next_action": "swarm_tick",
        }
    veto = supervision.check_veto(
        f"solidify:{run_id}",
        run_id,
        meta["gene_id"],
        meta["landed_gene_id"],
    )
    if veto is not None:
        return {
            "ok": False,
            "error": "supervision_veto",
            "veto": veto,
            "next_action": "swarm_tick",
        }

    with _capture_stdout() as capture:
        try:
            result = solidify(
                skip_validation=skip_validation,
                proposal=proposal,
                validation_scope=validation_scope,
                related_commands=related_commands,
            )
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
        err = str(result.get("error") or "")
        if err.startswith("hitl_"):
            status = err.removeprefix("hitl_")
            result["next_action"] = "await_human_approval" if status == "pending" else "swarm_tick"
        elif err == "supervision_paused":
            result["next_action"] = "await_supervisor_resume"
        elif err == "supervision_veto":
            result["next_action"] = "swarm_tick"
        if not result.get("ok") and "failure_mode" not in result:
            # The instrument prompt tells the host to read ``failure_mode`` —
            # make it real (tool-check 2026-09-05: the key was referenced but
            # never present, so the host could not decide retry vs stop).
            from evolver.gep.solidify import classify_failure_mode

            details = result.get("details")
            if err == "validation_failed" and isinstance(details, dict):
                mode = classify_failure_mode(validation=details.get("validation_result"))
            else:
                mode = {"mode": "hard", "reasonClass": err or "unknown", "retryable": False}
            result["failure_mode"] = mode
            result.setdefault(
                "next_action", "swarm_tick" if mode.get("retryable") else "stop_and_report"
            )
    if isinstance(result, dict) and result.get("event_id"):
        # 经验即证据 §5.1: the runtime records the settled round, Accept or
        # Reject, at the cycle boundary. The mutation path cannot (call-graph
        # pin). A record failure must not change the settlement outcome.
        from evolver.gep import episode_record

        try:
            result["episode"] = episode_record.record_round(event_id=str(result["event_id"]))
        except Exception as exc:
            result["episode"] = {"ok": False, "error": f"episode_record_failed: {exc}"}
    if isinstance(result, dict):
        try:
            from evolver.gep.compact_gate import note_outcome

            note_outcome(bool(result.get("ok")))
        except Exception:
            pass
    return result


def swarm_checkpoint_working(content: str) -> dict[str, Any]:
    """Crystallize session scratch and clear a pending compaction marker.

    The host writes the hypothesis, ruled-out approaches, and episode ids.
    Mutation tools stay refused until this succeeds while the marker is set.
    """
    from evolver.gep.compact_gate import clear_checkpoint
    from evolver.gep.working_memory import write_working

    try:
        written = write_working(content)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "checkpoint_rejected",
            "message": str(exc),
            "next_action": "call_swarm_checkpoint_working",
            "steer_message": (
                "Write a non-empty WORKING_SESSION.md within 16000 characters, "
                "then call swarm_checkpoint_working again."
            ),
        }
    cleared = clear_checkpoint()
    return {
        "ok": True,
        "path": written["path"],
        "chars": written["chars"],
        "redacted": written["redacted"],
        "checkpoint_cleared": cleared,
        "source": "host_working",
        "next_action": "compact_or_new_session",
        "steer_message": (
            "WORKING_SESSION.md is saved. Compact or open a new session. "
            "swarm_boot reloads this scratch; it is a clue, not a gate input."
        ),
    }


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


def host_relay_blocked() -> bool:
    """True when unattended takeover must not accept host-relayed human acts."""
    from evolver.config import SWARM_AUTO_HIJACK

    return bool(SWARM_AUTO_HIJACK)


def swarm_supervise(
    action: Literal["status", "pause", "resume", "direct", "veto", "unveto"],
    text: str | None = None,
    pattern: str | None = None,
    veto_id: str | None = None,
    reason: str = "",
    note: str = "",
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
        return supervision.add_veto(pattern or "", by=by, note=note)
    if action == "unveto":
        return supervision.remove_veto(veto_id or "")
    return {"ok": False, "error": f"unknown_action:{action}"}


_HOOK_EVENTS: Final = ("session_start", "session_end", "signal_detect", "precompact")


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
    from evolver.gep.asset_store import append_jsonl, append_pending_signals
    from evolver.gep.paths import get_evolution_dir

    if event not in _HOOK_EVENTS:
        return {
            "ok": False,
            "error": f"unknown_event:{event}",
            "supported": list(_HOOK_EVENTS),
        }
    if event == "precompact":
        from evolver.gep.compact_gate import request_checkpoint

        path = request_checkpoint("precompact")
        return {
            "ok": True,
            "event": event,
            "source": source,
            "marker": str(path),
            "next_action": "call_swarm_checkpoint_working",
            "steer_message": (
                "Compaction was requested. Call swarm_checkpoint_working before any mutation tool."
            ),
        }
    content, file_path = _extract_content(payload or {})
    signals = detect_signals(content)
    if signals:
        append_pending_signals(signals)
    trajectory_recorded = False
    if event == "session_end":
        with contextlib.suppress(Exception):
            from evolver.gep.cursor import record_trajectory

            record_trajectory(1)
            trajectory_recorded = True
    entry = {
        "event": event,
        "source": source,
        "signals": signals,
        "file_path": file_path or None,
        "at": _dt.datetime.now(_dt.UTC).isoformat(),
    }
    with contextlib.suppress(OSError):
        # Locked + closed append (DEBUG #54 family): the daemon loop and the
        # MCP server are two live processes writing JSONL, and a bare
        # open().write() without close can lose the tail on crash.
        append_jsonl(get_evolution_dir() / "hook_events.jsonl", entry)
    out: dict[str, Any] = {
        "ok": True,
        "event": event,
        "source": source,
        "detected_signals": signals,
        "injected": signals,
        "file_path": file_path or None,
        "note": "" if signals else "no signals detected — nothing injected",
    }
    if trajectory_recorded:
        out["trajectory_recorded"] = True
    return out


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


def swarm_skills(
    action: Literal["scan", "list", "sync"],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Skill ecosystem bridge (EvoX SkillRegistry concept harvest).

    ``scan`` discovers host skills (project > user > builtin, same-name
    shadowing); ``list`` shows skill-derived genes already in the store;
    ``sync`` converts + installs them so skills participate in selection.
    """
    from evolver.gep import skill_assets

    if action == "scan":
        return {"ok": True, "skills": skill_assets.discover_skills()}
    if action == "list":
        return {"ok": True, "genes": skill_assets.list_skill_genes()}
    if action == "sync":
        return skill_assets.sync_skills(dry_run=dry_run)
    return {"ok": False, "error": f"unknown_action:{action}"}


def swarm_workflow_run(
    file: str | None = None,
    template: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Start a durable workflow from a YAML/JSON spec file or bundled template.

    EvoX harvest: the collaboration is data — a YAML workflow whose agent
    steps declare roles the host executor picks up via ``swarm_workflow_status``.
    """
    from evolver.gep.workflow import WorkflowEngine, load_spec, load_template

    if bool(file) == bool(template):
        return {"ok": False, "error": "exactly one of file|template is required"}
    try:
        spec: dict[str, Any]
        if file is not None:
            spec = load_spec(Path(file))
        else:
            assert template is not None  # exactly-one guard above
            spec = load_template(template)
    except (OSError, FileNotFoundError) as exc:
        return {"ok": False, "error": f"spec_unreadable:{exc}"}
    if workflow_id:
        spec["id"] = workflow_id
    engine = WorkflowEngine()
    try:
        state = engine.create(spec)
        state = engine.run(state)
    except Exception as exc:  # surfaced to the host verbatim
        return {"ok": False, "error": f"workflow_error:{exc}"}
    result: dict[str, Any] = {
        "ok": True,
        "workflow_id": state.id,
        "status": state.status,
        "step": state.step_index,
        "steps": len(spec.get("steps", [])),
    }
    if state.status == "waiting_agent":
        result["awaiting_agent"] = engine.awaiting_agent(state.id)
    if state.status == "waiting_approval":
        result["awaiting_approval"] = engine.awaiting_approval(state.id)
    if state.error:
        result["error"] = state.error
    return result


def swarm_workflow_act(
    workflow_id: str,
    action: Literal["approve", "reject", "complete", "resume", "cancel"],
    result: Any = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Advance a waiting workflow: approve/reject approvals, complete agent
    steps (host reports the mutation result), resume retries, cancel."""
    from evolver.gep.workflow import WorkflowEngine, WorkflowPermanentError

    engine = WorkflowEngine()
    try:
        if action == "approve":
            state = engine.approve(workflow_id, note=note)
        elif action == "reject":
            state = engine.reject(workflow_id, note=note)
        elif action == "complete":
            state = engine.complete_agent(workflow_id, result)
        elif action == "resume":
            state = engine.resume(workflow_id)
        elif action == "cancel":
            state = engine.cancel(workflow_id)
        else:
            return {"ok": False, "error": f"unknown_action:{action}"}
    except (WorkflowPermanentError, LookupError) as exc:
        return {"ok": False, "error": str(exc)}
    out: dict[str, Any] = {
        "ok": True,
        "workflow_id": state.id,
        "status": state.status,
        "step": state.step_index,
    }
    if state.status == "waiting_agent":
        out["awaiting_agent"] = engine.awaiting_agent(state.id)
    if state.status == "waiting_approval":
        out["awaiting_approval"] = engine.awaiting_approval(state.id)
    if state.error:
        out["error"] = state.error
    return out


def swarm_workflow_status(
    workflow_id: str,
) -> dict[str, Any]:
    """Full state of one workflow run, including what the host should do now."""
    from evolver.gep.workflow import WorkflowEngine

    engine = WorkflowEngine()
    try:
        state = engine.load(workflow_id)
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    out: dict[str, Any] = {"ok": True, **engine.status(workflow_id)}
    if state.status == "waiting_agent":
        out["awaiting_agent"] = engine.awaiting_agent(workflow_id)
    if state.status == "waiting_approval":
        out["awaiting_approval"] = engine.awaiting_approval(workflow_id)
    return out


async def swarm_host_round(
    agent_name: str = "host-agent",
    project: str | Path | None = None,
    *,
    include_prompt: bool = True,
) -> dict[str, Any]:
    """U-12: Single-entry host protocol runner (boot -> state_health -> tick -> checklist)."""
    boot = swarm_boot(agent_name=agent_name, project=project)
    state = boot.get("state") or {}
    next_act = str(boot.get("next_action") or "swarm_tick")
    tick_res: dict[str, Any] | None = None
    checklist: dict[str, Any]
    if next_act == "swarm_tick":
        tick_res = await swarm_tick(agent_name=agent_name, include_prompt=include_prompt)
        checklist = tick_res.get("checklist") or _build_tick_checklist(
            run_id=tick_res.get("run_id"),
            selected_gene=tick_res.get("selected_gene"),
            proposal_required=bool(tick_res.get("proposal_required")),
        )
        next_act = str(tick_res.get("next_action") or next_act)
    else:
        meta = _pending_solidify_meta()
        checklist = _build_tick_checklist(
            run_id=meta.get("run_id") or None,
            selected_gene={"id": meta.get("gene_id")} if meta.get("gene_id") else None,
            proposal_required=False,
        )

    return {
        "ok": True,
        "mode": "host_round",
        "agent_name": agent_name,
        "repo_root": state.get("repo_root"),
        "workspace_id": state.get("workspace_id"),
        "state_root": state.get("state_root"),
        "mismatch": state.get("mismatch"),
        "state_health": state.get("state_health"),
        "boot_next_action": boot.get("next_action"),
        "next_action": next_act,
        "tick": tick_res,
        "checklist": checklist,
    }


__all__ = [
    "SWARM_PROTOCOL_VERSION",
    "build_instrument_prompt",
    "swarm_boot",
    "swarm_checkpoint_working",
    "swarm_distill",
    "swarm_feedback",
    "swarm_hook_event",
    "swarm_hooks",
    "swarm_host_round",
    "swarm_propose",
    "swarm_report",
    "swarm_skills",
    "swarm_solidify",
    "swarm_status",
    "swarm_supervise",
    "swarm_tick",
    "swarm_workflow_act",
    "swarm_workflow_run",
    "swarm_workflow_status",
]
