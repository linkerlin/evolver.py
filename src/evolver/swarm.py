"""Swarm evolution — atomic FSM host-agent orchestration (算子即基因 v1.114.0).

Implements the zero-cognitive-load 3-tool FSM protocol over transport-agnostic
Python functions (surfaced via MCP stdio in :mod:`evolver.mcp_server`):

- ``IDLE``       : ``evolve_begin`` + ``evolve_status``
- ``ACTIVE_RUN`` : ``run_lens`` + ``evolve_settle`` + ``evolve_status``

Key guarantees:
1. **Zero JSON ceremony**: ``evolve_begin(hypothesis="...")`` accepts a plain
   one-sentence string, lazily bootstraps native baselines if absent, discovers
   workspace signals, synthesizes the internal §5.3 hypothesis record, and opens
   the cycle-boundary in-band blackbox.
2. **No whack-a-mole redirect flags**: ``pending_tick_redirects.json`` and the
   17 legacy boolean steering flags are eliminated; the FSM physically hides
   ``evolve_begin`` while ``_pending_solidify_state()`` is ``True``.
3. **Dual-track settlement**: ``evolve_settle`` runs ``< 3s`` AST reverse-dep
   L0 lightning validation by default, settles the blackbox, records the
   immutable ``episode_record`` at this declared cycle boundary, preserves
   failed patches in place with a 3-line ``actionable_fix``, and promotes only
   all-green net gains to the vault.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import re
import secrets
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final, Literal

SWARM_PROTOCOL_VERSION: Final = "2"

_SWARM_STATE_FILENAME: Final = "swarm_state.json"
_ABORT_REASON_RE: Final = re.compile(r"Preflight abort: (.+)")
_hello_sent: set[str] = set()
_session_claim: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Low-level helpers
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


def _feedback_stability(rows: list[dict[str, Any]], window: int = 10) -> dict[str, Any] | None:
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
    try:
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
    pkg_dir = Path(__file__).resolve().parent
    candidates = [pkg_dir.parents[1], pkg_dir.parents[2], pkg_dir.parent, pkg_dir]
    for root in candidates:
        if (root / ".git").exists():
            return root
    for parent in pkg_dir.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _source_revision() -> str | None:
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
    return {
        "ok": False,
        "error": "code_stale_process",
        "reason": str(exc)[:300],
        "next_action": "reconnect_host",
        "hint": (
            "This MCP process predates the current src tree; restart/reconnect "
            "the host so a fresh process loads matching code."
        ),
    }


def _pending_solidify_state() -> bool:
    """True iff solidify state holds an unsettled ``last_run`` (Anchor DEBUG #9).

    Corrupt state fails safe toward ``True`` (ACTIVE_RUN -> settle required).
    File existence alone never reports pending.
    """
    from evolver.gep.paths import get_solidify_state_path

    path = get_solidify_state_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    last_run_id = str((data.get("last_run") or {}).get("run_id") or "")
    last_done_id = str((data.get("last_solidify") or {}).get("run_id") or "")
    return bool(last_run_id) and last_run_id != last_done_id


def fsm_state() -> Literal["IDLE", "ACTIVE_RUN"]:
    """Authoritative FSM state derived from ``_pending_solidify_state()``."""
    return "ACTIVE_RUN" if _pending_solidify_state() else "IDLE"


def _pending_solidify_meta() -> dict[str, str]:
    from evolver.gep.paths import get_solidify_state_path

    try:
        data = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
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


def _bench_gate_snapshot() -> dict[str, Any]:
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


def _working_snapshot() -> dict[str, Any]:
    try:
        from evolver.gep.compact_gate import checkpoint_pending
        from evolver.gep.working_memory import read_working

        text = read_working()
        has_text = bool(text.strip())
        return {
            "present": has_text,
            "exists": has_text,
            "chars": len(text),
            "preview": text[:400],
            "compact_checkpoint_pending": checkpoint_pending(),
        }
    except Exception:
        return {
            "present": False,
            "exists": False,
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
        "fsm_state": "IDLE",
        "run_id": run_id,
        "episode_id": ep_id,
        "episode": {"ok": True, "reason": "already_stored", "id": ep_id},
        "next_action": "evolve_begin",
        "steer_message": (
            "This run_id is already settled. Call evolve_begin to start a new evolution run."
        ),
    }


def bind_project_directory(project: str | Path | None) -> dict[str, Any]:
    """Point the process at ``project`` only when that path is an existing directory."""
    if project is None or not str(project).strip():
        return {"project": None, "project_applied": False, "project_reason": "not_requested"}
    raw = str(project).strip()
    resolved = Path(raw).expanduser().resolve()
    if not resolved.is_dir():
        return {
            "project": raw,
            "project_resolved": str(resolved),
            "project_applied": False,
            "project_reason": "not_a_directory",
        }
    os.environ["EVOLVER_REPO_ROOT"] = str(resolved)
    os.environ["OPENCLAW_WORKSPACE"] = str(resolved)
    return {
        "project": raw,
        "project_resolved": str(resolved),
        "project_applied": True,
        "project_reason": "bound_existing_directory",
    }


def describe_bound_paths(bind: dict[str, Any] | None = None) -> dict[str, Any]:
    from evolver.gep.paths import get_repo_root, get_workspace_root

    workspace = get_workspace_root().resolve()
    repo = get_repo_root(_quiet=True)
    repo_text = str(repo.resolve()) if repo is not None else ""
    differ = repo is not None and repo.resolve() != workspace
    out: dict[str, Any] = {
        "repo_root": repo_text,
        "workspace_root": str(workspace),
        "code_root": repo_text or str(workspace),
        "differ": differ,
    }
    if bind is not None:
        out["project"] = bind.get("project")
        out["project_resolved"] = bind.get("project_resolved")
        out["project_applied"] = bool(bind.get("project_applied"))
        out["project_reason"] = bind.get("project_reason")
    if bind is not None and bind.get("project_reason") == "not_a_directory":
        out["warning"] = f"project {bind.get('project')!r} is not an existing directory."
    elif differ:
        out["warning"] = f"workspace_root ({workspace}) != repo_root ({repo_text})."
    return out


def _maybe_lazy_bootstrap() -> None:
    """Lazily dispatch clean background native-baseline bootstrap on uninitialized repos."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from evolver.gep.paths import get_repo_root, get_workspace_state_dir

        repo = get_repo_root(_quiet=True)
        if repo is None:
            return
        marker = get_workspace_state_dir(repo) / "bootstrap_baseline.json"
        if marker.exists():
            return
        from evolver.ops.init_bootstrap import bootstrap

        bootstrap(project=repo, yes=False, spawn=True, configure_hosts=False)
    except Exception:
        pass


def _opening_action(state: dict[str, Any]) -> tuple[str, str]:
    if state.get("pending_solidify") or state.get("fsm_state") == "ACTIVE_RUN":
        return (
            "evolve_settle",
            (
                "当前存在活跃进化轮次（ACTIVE_RUN）：使用 `run_lens` 诊断或修改代码后，"
                "调用 `evolve_settle` 一键验证结算。"
            ),
        )
    supervision = state.get("supervision")
    if isinstance(supervision, dict) and supervision.get("state") == "paused":
        return (
            "await_supervisor_resume",
            "人工监督已暂停进化循环；待用户指示继续后再启动新一轮。",
        )
    return (
        "evolve_begin",
        "调用 `evolve_begin(hypothesis='一句话描述本轮唯一修复/优化假说')` 开启原子进化轮次。",
    )


# ---------------------------------------------------------------------------
# Instrument prompt (concise 3-tool FSM protocol)
# ---------------------------------------------------------------------------


def build_instrument_prompt(state: dict[str, Any] | None = None) -> str:
    """Render the concise zero-jargon 3-tool FSM takeover prompt."""
    from evolver.gep.lenses import BUILTIN_LENSES
    from evolver.gep.prompt import CHARTER_PREAMBLE

    st = state if isinstance(state, dict) else evolve_status()
    agent = str(st.get("agent_name") or "host-agent")
    workspace = str(st.get("repo_root") or st.get("workspace_root") or "(workspace)")
    cur_fsm = str(st.get("fsm_state") or fsm_state())
    next_act, prose = _opening_action(st)
    lens_names = ", ".join(sorted(BUILTIN_LENSES))

    working = st.get("working_session") if isinstance(st.get("working_session"), dict) else {}
    preview = str((working or {}).get("preview") or "").strip()
    working_block = f"\n## 当轮工作草稿 (WORKING_SESSION.md)\n{preview}\n" if preview else ""

    body_lines = [
        f"# EVOLVER SWARM — 零干预三工具原子协议 (v{SWARM_PROTOCOL_VERSION})",
        "",
        f"> 你（{agent}）已连接 evolver 自进化引擎（工作区：`{workspace}`）。",
        "> 若用户当前消息已有明确其他任务，优先完成用户任务；否则按以下三步状态机闭环执行。",
        "",
        "## 宪章",
        "",
        CHARTER_PREAMBLE,
        "",
        f"## 三步状态机协议（FSM = `{cur_fsm}`，下一步：`{next_act}`）",
        "",
        '1. **`evolve_begin(hypothesis="...")`**（仅 `IDLE` 态可见）',
        "   - 传入**一句话清晰假说**，说明本轮准备验证的唯一改动（无需手写 JSON 模板或题号）。",
        "   - 引擎自动完成基线懒自举、信号发现、算子匹配，并开启黑匣子切换至 `ACTIVE_RUN`。",
        '2. **`run_lens(name="...", target="...")` + 编辑代码**（`ACTIVE_RUN` 态）',
        f"   - 可选只读诊断透镜：`{lens_names}`",
        "     （`import_impact` 查受影响单测，`ast_hotspot` 查异常吞没，`trace_locator` 定位栈）。",
        f"   - 仅在 `{workspace}` 内做聚焦、单组件最小代码修改（严禁手改运行态目录）。",
        '3. **`evolve_settle(summary="...")`**（仅 `ACTIVE_RUN` 态可见）',
        "   - 默认运行 `< 3s` AST 反向依赖图 **L0 闪电验证**并记录 `episode_record` 与黑匣子。",
        "   - **双轨裁决**：",
        '     - 全绿净增益（`ok=true, outcome="promoted"`）：经验自动晋升金库，切回 `IDLE`。',
        '     - 验证未过或未胜（`ok=false, outcome="draft_preserved"`）：补丁原位保留，',
        "       返回精确到行号的 3 行 `actionable_fix`，不污染金库；按指引修复后再验证即可。",
        "     - 首轮缺口（`pack_absent` / `no_baseline` / `unmeasured`）`soft-continue`，",
        "       不写基线不自动提交；硬阻断仅限密钥（secrets）、`~/.evolver/` 与 `val_seal`。",
        "",
        f"当前指引：{prose}{working_block}",
    ]
    return "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# First-class 3-tool FSM orchestrators (P1-1 + P1-2)
# ---------------------------------------------------------------------------


def _discover_workspace_signals() -> list[str]:
    """Best-effort fast read of pending workspace signals without side effects."""
    try:
        from evolver.gep.paths import get_gep_assets_dir

        pending_file = get_gep_assets_dir() / "pending_signals.json"
        if pending_file.is_file():
            data = json.loads(pending_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("signals"), list):
                return [str(s) for s in data["signals"] if str(s).strip()][:12]
    except Exception:
        pass
    return []


def _discover_recommended_operators(signals: list[str]) -> list[dict[str, Any]]:
    """Match active vault genes/operators against *signals* for zero-side-effect preview."""
    try:
        from evolver.gep.asset_store import load_genes
        from evolver.gep.index_db import query_operator_stats

        op_stats_map: dict[str, dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            for row in query_operator_stats(limit=100, auto_sync=False):
                gid = str(row.get("gene_id") or "")
                if gid:
                    op_stats_map[gid] = row

        sig_set = {s.lower() for s in signals}
        scored: list[tuple[float, dict[str, Any]]] = []
        for g in load_genes():
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "")
            g_sigs = [str(x).lower() for x in (g.get("signals_match") or [])]
            hits = sum(1 for x in g_sigs if x in sig_set)
            st = op_stats_map.get(gid) or {}
            helped_bonus = min(0.5, 0.1 * int(st.get("helped") or 0))
            hit_rate = st.get("hit_rate")
            rate_bonus = 0.2 * float(hit_rate) if isinstance(hit_rate, int | float) else 0.0
            scored.append(
                (
                    float(hits) + helped_bonus + rate_bonus,
                    {
                        "id": gid,
                        "category": str(g.get("category") or "repair"),
                        "summary": str(g.get("summary") or g.get("description") or "")[:160],
                        "has_lens": bool(g.get("lens")),
                        "hit_rate": hit_rate,
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:3]]
    except Exception:
        return []


def _infer_dimension(target_files: list[str] | None, hypothesis_text: str) -> str:
    joined = " ".join(target_files or []).lower() + " " + hypothesis_text.lower()
    if any(tok in joined for tok in ("schema", "pydantic", "model")):
        return "schema"
    if any(tok in joined for tok in ("mcp", "cli", "hook", "adapter", "lens", "tool")):
        return "tool"
    return "content"


def _synthesize_internal_hypothesis(
    hypothesis_text: str,
    *,
    run_id: str,
    target_files: list[str] | None = None,
    selected_gene_id: str | None = None,
) -> dict[str, Any]:
    """Synthesize a §5.3-compliant internal hypothesis record from a plain sentence."""
    from evolver.gep.val_seal import assert_sealed, task_ids

    clean = hypothesis_text.strip()
    assert_sealed(clean, where="dispatch")

    buckets = task_ids()
    train_ids = buckets.get("train") or []
    check_id = str(train_ids[0]) if train_ids else "native-baseline"
    hook = (
        str(target_files[0]).replace("\\", "/").strip()
        if target_files and str(target_files[0]).strip()
        else "workspace"
    )
    family = str(selected_gene_id or "").strip() or "operator_repair"
    return {
        "run_id": run_id,
        "hypothesis": clean,
        "dimension": _infer_dimension(target_files, clean),
        "mechanism_family": family,
        "target_hook": hook,
        "mechanism_check": [
            {
                "id": check_id,
                "before": "observed pre-change baseline or failure signal in workspace",
                "after": clean[:240],
            }
        ],
    }


def evolve_status(project: str | Path | None = None) -> dict[str, Any]:
    """Read-only unified status for both MCP agents and humans (no cycle side effects)."""
    from evolver import __version__
    from evolver.gep.blackbox import load_active_blackbox
    from evolver.gep.lenses import BUILTIN_LENSES
    from evolver.gep.paths import get_repo_root, get_workspace_root
    from evolver.gep.supervision import supervision_summary
    from evolver.ops.status_human import human_status

    bind = bind_project_directory(project) if project else None
    repo = get_repo_root(_quiet=True) or get_workspace_root()
    panel = human_status(project=repo)
    cur_fsm = fsm_state()
    meta = _pending_solidify_meta() if cur_fsm == "ACTIVE_RUN" else {}
    active_bb = load_active_blackbox() if cur_fsm == "ACTIVE_RUN" else None
    sup = supervision_summary()

    out: dict[str, Any] = {
        "ok": True,
        "version": __version__,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "fsm_state": cur_fsm,
        "allowed_tools": (
            ["run_lens", "evolve_settle", "evolve_status"]
            if cur_fsm == "ACTIVE_RUN"
            else ["evolve_begin", "evolve_status"]
        ),
        "active_run_id": meta.get("run_id") or None,
        "selected_gene_id": meta.get("gene_id") or None,
        "ready": bool(panel.get("ready")),
        "lamp": panel.get("lamp"),
        "headline": panel.get("headline"),
        "promoted": panel.get("promoted", 0),
        "soft_accepted": panel.get("soft_accepted", 0),
        "intercepted": panel.get("intercepted", 0),
        "saved_validation_seconds": panel.get("saved_validation_seconds"),
        "vault_operators": panel.get("vault_operators", 0),
        "vault_capsules": panel.get("vault_capsules", 0),
        "workbench_drafts": panel.get("workbench_drafts", 0),
        "repo_root": str(repo),
        "workspace_id": panel.get("workspace_id"),
        "state_dir": panel.get("state_dir"),
        "top_signals": _discover_workspace_signals(),
        "available_lenses": sorted(BUILTIN_LENSES),
        "active_blackbox": (
            {
                "run_id": active_bb.get("run_id"),
                "started_at": active_bb.get("started_at"),
                "lens_calls_count": len(active_bb.get("lens_calls") or []),
            }
            if isinstance(active_bb, dict)
            else None
        ),
        "supervision": sup,
        "working_session": _working_snapshot(),
        "bound_paths": describe_bound_paths(bind),
    }
    next_act, prose = _opening_action({"fsm_state": cur_fsm, "supervision": sup})
    out["next_action"] = next_act
    out["hint"] = prose
    return out


def _has_valid_active_hypothesis() -> bool:
    """True iff the current pending run already has a valid §5.3 hypothesis."""
    if not _pending_solidify_state():
        return False
    run_id = _pending_solidify_meta().get("run_id") or ""
    if not run_id:
        return False
    try:
        from evolver.gep.hypothesis import load_hypothesis, require_for_gate
        from evolver.gep.solidify import _session_round_scopes

        declared = load_hypothesis()
        require_for_gate(
            declared,
            run_id=run_id,
            also_accept=_session_round_scopes(),
        )
        return True
    except Exception:
        return False


async def evolve_begin(
    hypothesis: str = "",
    *,
    target_files: list[str] | None = None,
    auto_discover: bool = True,
    discard_draft: bool = False,
    force_takeover: bool = False,
    project: str | Path | None = None,
    agent_name: str = "host-agent",
) -> dict[str, Any]:
    """Atomically start one evolution run, lock its single hypothesis, and enter ``ACTIVE_RUN``."""
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep import supervision
    from evolver.gep.blackbox import begin_blackbox
    from evolver.gep.hypothesis import record_hypothesis
    from evolver.gep.lenses import BUILTIN_LENSES
    from evolver.gep.paths import ensure_workspace_meta, get_repo_root, get_workspace_root
    from evolver.gep.val_seal import ValSealBreachError

    bind = bind_project_directory(project) if project else None
    with contextlib.suppress(Exception):
        ensure_workspace_meta()
    _maybe_lazy_bootstrap()

    global _session_claim
    _session_claim = {"agent_name": str(agent_name or "host-agent")}

    clean_hyp = (hypothesis or "").strip()
    taking_over = bool(force_takeover and _pending_solidify_state())
    if _pending_solidify_state() and not force_takeover:
        meta = _pending_solidify_meta()
        return {
            "ok": False,
            "error": "fsm_state_mismatch",
            "fsm_state": "ACTIVE_RUN",
            "active_run_id": meta.get("run_id") or None,
            "allowed_tools": ["run_lens", "evolve_settle", "evolve_status"],
            "next_action": "evolve_settle",
            "message": (
                "An evolution run is already active. Call `evolve_settle` to validate/close it "
                "(pass `hypothesis='...'` if the run came from CLI without one, or `abandon=True` "
                "to close without validating), or call `evolve_begin(hypothesis='...', "
                "force_takeover=True)` to replace a wedged run."
            ),
        }

    if force_takeover and not clean_hyp:
        return {
            "ok": False,
            "error": "empty_hypothesis",
            "fsm_state": fsm_state(),
            "next_action": "evolve_settle" if _pending_solidify_state() else "evolve_begin",
            "message": (
                "Pass a non-empty one-sentence `hypothesis` when using `force_takeover=True`."
            ),
        }

    tripwire = supervision.auto_pause_check()
    if supervision.is_paused():
        return {
            "ok": False,
            "paused": True,
            "error": "supervision_paused",
            "fsm_state": fsm_state(),
            "supervision": supervision.supervision_summary(),
            "tripwire": tripwire,
            "next_action": "await_supervisor_resume",
            "message": "Evolution loop is paused by human supervision.",
        }

    if not clean_hyp:
        sigs = _discover_workspace_signals()
        if auto_discover:
            recs = _discover_recommended_operators(sigs)
            top_sig = sigs[0] if sigs else "workspace defect or optimization target"
            return {
                "ok": True,
                "discovery_only": True,
                "fsm_state": "IDLE",
                "top_signals": sigs,
                "recommended_operators": recs,
                "available_lenses": sorted(BUILTIN_LENSES),
                "hypothesis_template": (
                    f"Fix/improve {top_sig} in <module> so <specific check> passes."
                ),
                "next_action": "evolve_begin",
                "message": (
                    "Candidate signals and operators discovered. Call "
                    "`evolve_begin(hypothesis='...')` with a one-sentence falsifiable "
                    "hypothesis to lock the round and enter ACTIVE_RUN."
                ),
            }
        return {
            "ok": False,
            "error": "empty_hypothesis",
            "fsm_state": "IDLE",
            "top_signals": sigs,
            "next_action": "evolve_begin",
            "message": (
                "Pass a non-empty one-sentence `hypothesis` stating the single "
                "mechanism or bug fix you intend to validate this round."
            ),
        }

    # Auto-satisfy compaction scratch checkpoint using the host's explicit hypothesis
    from evolver.gep.compact_gate import checkpoint_pending, clear_checkpoint
    from evolver.gep.working_memory import write_working

    if checkpoint_pending():
        with contextlib.suppress(Exception):
            write_working(f"# Active Hypothesis\n\n{clean_hyp}\n")
            clear_checkpoint()

    cwd = (get_repo_root(_quiet=True) or get_workspace_root()).resolve()
    if discard_draft:
        with contextlib.suppress(Exception):
            from evolver.gep.git_ops import rollback_tracked

            rollback_tracked(cwd=cwd, include_untracked=False)

    # Validate val_seal before touching any cycle state
    try:
        probe_payload = _synthesize_internal_hypothesis(
            clean_hyp,
            run_id="run_preflight",
            target_files=target_files,
        )
    except ValSealBreachError as exc:
        return {
            "ok": False,
            "error": "val_seal_breach",
            "fsm_state": fsm_state(),
            "message": str(exc),
            "next_action": "evolve_begin",
        }
    _ = probe_payload

    from evolver.evolve.runner import _run_single_cycle
    from evolver.gep.instance_lock import instance_lock_ctx
    from evolver.gep.solidify import write_state_for_solidify

    ctx: dict[str, Any] = {}
    engine_log = ""
    with instance_lock_ctx(blocking=False, timeout=0) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "instance_lock_held",
                "fsm_state": fsm_state(),
                "next_action": "stop_and_report",
                "message": "Another evolver process holds the workspace lock.",
            }
        if auto_discover:
            with _capture_stdout() as capture:
                try:
                    ctx = await _run_single_cycle(is_loop=False)
                except Exception as exc:
                    ctx = {"cycle_warning": str(exc)[:240]}
            engine_log = capture.getvalue()

        if ctx.get("autopoiesis_preflight_abort"):
            abort_reason = (
                m.group(1) if (m := _ABORT_REASON_RE.search(engine_log)) else "preflight_abort"
            )
            return {
                "ok": False,
                "error": "preflight_abort",
                "abort_reason": abort_reason,
                "fsm_state": fsm_state(),
                "next_action": "stop_and_report",
            }

        gene = ctx.get("selected_gene") if isinstance(ctx.get("selected_gene"), dict) else None
        selected_gene_id = str(gene.get("id") or "") if isinstance(gene, dict) else ""
        signals = (
            [str(s) for s in ctx.get("signals", []) if str(s).strip()]
            if isinstance(ctx.get("signals"), list)
            else _discover_workspace_signals()
        )

        # Guarantee deterministic transition (or clean takeover) into ACTIVE_RUN
        ctx_run_id = str(ctx.get("run_id") or "")
        cur_meta = _pending_solidify_meta()
        dispatched_fresh = bool(ctx_run_id) and cur_meta.get("run_id") == ctx_run_id
        if dispatched_fresh:
            run_id = ctx_run_id
        elif taking_over or not _pending_solidify_state() or not cur_meta.get("run_id"):
            run_id = f"run_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
            write_state_for_solidify(
                {
                    "run_id": run_id,
                    "selected_gene_id": selected_gene_id or None,
                    "signals": signals,
                    "mutation": {
                        "id": f"mut_{run_id}",
                        "category": "repair",
                        "validation": [],
                    },
                }
            )
        else:
            run_id = cur_meta["run_id"]
            if not selected_gene_id:
                selected_gene_id = cur_meta["gene_id"]

        hyp_record = _synthesize_internal_hypothesis(
            clean_hyp,
            run_id=run_id,
            target_files=target_files,
            selected_gene_id=selected_gene_id or None,
        )
        record_hypothesis(hyp_record)
        bb = begin_blackbox(
            run_id,
            cwd,
            hypothesis=clean_hyp,
            selected_gene_id=selected_gene_id,
        )

    dispatch_prompt = (
        str(ctx.get("dispatch_prompt") or "").strip()
        if isinstance(ctx.get("dispatch_prompt"), str)
        else ""
    )
    _record_tick(
        {
            "run_id": run_id,
            "cycle_id": ctx.get("cycle_id"),
            "agent_name": agent_name,
            "preflight_aborted": False,
            "dispatch_reason": "evolve_begin",
            "selected_gene": {"id": selected_gene_id} if selected_gene_id else None,
            "proposal_required": False,
            "next_action": "evolve_settle",
        }
    )

    out: dict[str, Any] = {
        "ok": True,
        "fsm_state": "ACTIVE_RUN",
        "run_id": run_id,
        "hypothesis": clean_hyp,
        "repo_root": str(cwd),
        "selected_gene": (
            {
                "id": gene.get("id"),
                "name": gene.get("name") or gene.get("summary"),
                "category": gene.get("category"),
            }
            if isinstance(gene, dict)
            else None
        ),
        "routing_advice": _compute_round_routing_advice(gene),
        "structure_mirror": _safe_structure_mirror(),
        "signals": signals[:12],
        "available_lenses": sorted(BUILTIN_LENSES),
        "blackbox_started_at": bb.get("started_at"),
        "dispatch_context": _tail(dispatch_prompt, 4000) if dispatch_prompt else None,
        "engine_log": _tail(engine_log, SWARM_TICK_LOG_MAX_CHARS) if engine_log else "",
        "bound_paths": describe_bound_paths(bind),
        "next_action": "evolve_settle",
        "hint": (
            "ACTIVE_RUN started. Optional: call `run_lens` to inspect AST hotspots "
            "or impacted tests, apply your focused edit, then call `evolve_settle`."
        ),
    }
    if taking_over:
        out["taken_over"] = True
    return out


def evolve_run_lens(
    name: str = "list",
    target: str = ".",
    args: dict[str, Any] | None = None,
    *,
    project: str | Path | None = None,
) -> dict[str, Any]:
    """Run a read-only diagnostic lens during ``ACTIVE_RUN`` and log to the blackbox."""
    from evolver.gep.blackbox import record_lens_call
    from evolver.gep.lenses import run_lens
    from evolver.gep.paths import get_repo_root, get_workspace_root

    if project:
        bind_project_directory(project)
    root = (get_repo_root(_quiet=True) or get_workspace_root()).resolve()
    res = run_lens(name=name, target=target, args=args, repo_root=root)
    record_lens_call(
        name=str(res.get("lens") or name),
        target=target,
        ok=bool(res.get("ok")),
        duration_ms=int(res.get("duration_ms") or 0),
        summary=str(res.get("summary") or ""),
    )
    res["fsm_state"] = fsm_state()
    return res


def _compute_round_routing_advice(gene: dict[str, Any] | None) -> dict[str, Any]:
    try:
        from evolver.gep.blackbox import load_blackbox_telemetry
        from evolver.gep.router import compute_routing_advice

        consec = 0
        for row in reversed(load_blackbox_telemetry()[-5:]):
            if row.get("outcome_ok") is True or row.get("outcome_label") == "promoted":
                break
            consec += 1
        return compute_routing_advice(gene, consecutive_failures=consec)
    except Exception:
        return {"tier": "mid", "reasoning_level": "medium", "tier_weight": 2.83, "escalated": False}


def _safe_structure_mirror() -> str:
    try:
        from evolver.gep.blackbox import render_mutation_structure_mirror

        return render_mutation_structure_mirror()
    except Exception:
        return ""


_RAW_BENCH_MASK_KEYS: Final[tuple[str, ...]] = (
    "score",
    "baseline",
    "delta",
    "per_task",
    "rounds",
    "previous_baseline",
)


def _attach_host_direction(result: dict[str, Any]) -> None:
    """Apply S-6 directional feedback masking on the MCP host-facing bench_pack envelope."""
    bp = result.get("bench_pack")
    if not isinstance(bp, dict):
        return
    try:
        from evolver.bench.frozen_gate import direction_envelope_for_host

        val_dur = result.get("validation_duration_ms")
        dir_env = direction_envelope_for_host(
            bp,
            duration_ms=int(val_dur) if isinstance(val_dur, int | float) else None,
        )
        result["gate_direction"] = dir_env
        masked = {k: v for k, v in bp.items() if k not in _RAW_BENCH_MASK_KEYS}
        masked["val_direction"] = dir_env["val_direction"]
        masked["cost_direction"] = dir_env["cost_direction"]
        result["bench_pack"] = masked
    except Exception:
        # Fail-closed: strip raw float scores even if envelope formatting errors.
        masked = {k: v for k, v in bp.items() if k not in _RAW_BENCH_MASK_KEYS}
        masked["val_direction"] = "unmeasured"
        masked["cost_direction"] = "unmeasured"
        result["bench_pack"] = masked


def evolve_settle(
    summary: str = "",
    *,
    hypothesis: str = "",
    abandon: bool = False,
    validation_scope: str = "auto",
    related_commands: list[list[str]] | None = None,
    proposal: dict[str, Any] | None = None,
    restore_draft: bool = False,
    project: str | Path | None = None,
    agent_name: str = "host-agent",
) -> dict[str, Any]:
    """Validate, adjudicate, settle blackbox + episode record, and transition back to ``IDLE``."""
    from evolver.gep import episode_clue
    from evolver.gep.blackbox import clear_active_blackbox
    from evolver.gep.paths import get_repo_root, get_solidify_state_path, get_workspace_root

    if project:
        bind_project_directory(project)

    if restore_draft:
        restored = swarm_solidify(restore_stash=True, agent_name=agent_name)
        restored["fsm_state"] = fsm_state()
        return restored

    if not _pending_solidify_state():
        return {
            "ok": False,
            "error": "fsm_state_mismatch",
            "fsm_state": "IDLE",
            "allowed_tools": ["evolve_begin", "evolve_status"],
            "next_action": "evolve_begin",
            "message": "No active evolution run to settle. Call `evolve_begin` first.",
        }

    meta = _pending_solidify_meta()
    run_id = meta.get("run_id") or ""
    repo_str = str((get_repo_root(_quiet=True) or get_workspace_root()).resolve())

    if not run_id:
        with contextlib.suppress(OSError):
            get_solidify_state_path().unlink()
        with contextlib.suppress(Exception):
            clear_active_blackbox()
        return {
            "ok": False,
            "error": "corrupt_run_state_reset",
            "fsm_state": fsm_state(),
            "repo_root": repo_str,
            "allowed_tools": ["evolve_begin", "evolve_status"],
            "next_action": "evolve_begin",
            "message": (
                "Corrupt pending run state was reset cleanly. "
                "Call `evolve_begin(hypothesis='...')` to start a fresh run."
            ),
        }

    if abandon:
        from evolver.gep.solidify import _mark_run_settled

        _mark_run_settled(run_id, "abandoned_by_host")
        with contextlib.suppress(Exception):
            clear_active_blackbox()
        return {
            "ok": True,
            "status": "abandoned",
            "outcome": "draft_preserved",
            "fsm_state": fsm_state(),
            "run_id": run_id,
            "repo_root": repo_str,
            "allowed_tools": ["evolve_begin", "evolve_status"],
            "next_action": "evolve_begin",
            "message": (
                "Active run closed without validation; workspace edits were preserved in place. "
                "Call `evolve_begin(hypothesis='...')` when ready."
            ),
        }

    clean_hyp = (hypothesis or "").strip()
    if not _has_valid_active_hypothesis():
        if clean_hyp:
            from evolver.gep.hypothesis import HypothesisError, record_hypothesis
            from evolver.gep.val_seal import ValSealBreachError

            try:
                hyp_record = _synthesize_internal_hypothesis(
                    clean_hyp,
                    run_id=run_id,
                    selected_gene_id=meta.get("gene_id") or None,
                )
                record_hypothesis(hyp_record)
            except (ValSealBreachError, HypothesisError) as exc:
                return {
                    "ok": False,
                    "error": (
                        "val_seal_breach"
                        if isinstance(exc, ValSealBreachError)
                        else "hypothesis_rejected"
                    ),
                    "fsm_state": fsm_state(),
                    "run_id": run_id,
                    "repo_root": repo_str,
                    "allowed_tools": ["run_lens", "evolve_settle", "evolve_status"],
                    "next_action": "evolve_settle",
                    "message": str(exc),
                }
        else:
            from evolver.gep.solidify import _mark_run_settled

            _mark_run_settled(run_id, "hypothesis_missing")
            with contextlib.suppress(Exception):
                clear_active_blackbox()
            return {
                "ok": False,
                "outcome": "draft_preserved",
                "error": "hypothesis_missing",
                "fsm_state": fsm_state(),
                "run_id": run_id,
                "repo_root": repo_str,
                "allowed_tools": ["evolve_begin", "evolve_status"],
                "next_action": "evolve_begin",
                "message": (
                    "This pending run had no locked hypothesis (left over from an unfinished "
                    "CLI cycle). Your workspace edits were preserved in place and the orphan "
                    "run is now closed."
                ),
                "actionable_fix": [
                    "Call `evolve_begin(hypothesis='one-sentence falsifiable claim')` "
                    "to lock your hypothesis.",
                    "Keep or refine your preserved workspace edits.",
                    "Call `evolve_settle(summary='...')` to validate and settle.",
                ],
                "next_steps": [
                    "Call `evolve_begin(hypothesis='...')` to open a properly hypothesized round.",
                    "Then call `evolve_settle(summary='...')` to validate your preserved edits.",
                ],
            }

    clean_summary = (summary or "").strip()
    if clean_summary:
        if "```json" in clean_summary:
            with contextlib.suppress(Exception):
                swarm_distill(clean_summary, dry_run=False)
        else:
            with contextlib.suppress(Exception):
                episode_clue.append_clue(clean_summary[:2000], source="host_settle")

    effective_scope = (validation_scope or "auto").strip() or "auto"
    result = swarm_solidify(
        agent_name=agent_name,
        proposal=proposal,
        validation_scope=effective_scope,
        related_commands=related_commands,
    )
    cur_fsm = fsm_state()
    result["fsm_state"] = cur_fsm
    result["repo_root"] = repo_str
    _attach_host_direction(result)
    if result.get("ok") is True:
        result["next_action"] = "evolve_begin"
        result.setdefault(
            "hint",
            "Run promoted to vault and settled. FSM returned to IDLE.",
        )
    else:
        result["next_action"] = "evolve_begin" if cur_fsm == "IDLE" else "evolve_settle"
    return result


# ---------------------------------------------------------------------------
# Engine / CLI internal building blocks (preserved for CLI & unit seams)
# ---------------------------------------------------------------------------


def _record_tick(result: dict[str, Any]) -> None:
    state = _load_swarm_state()
    state["ticks"] = int(state.get("ticks") or 0) + 1
    state["updated"] = datetime.datetime.now(datetime.UTC).isoformat()
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
    with contextlib.suppress(Exception):
        _save_swarm_state(state)


def swarm_status() -> dict[str, Any]:
    """Engine status dictionary (used by ``evolver://status`` and CLI diagnostics)."""
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
    pending = _pending_solidify_state()
    cur_fsm: Literal["IDLE", "ACTIVE_RUN"] = "ACTIVE_RUN" if pending else "IDLE"
    sup = supervision_summary()
    next_act, prose = _opening_action({"pending_solidify": pending, "supervision": sup})

    return {
        "ok": True,
        "version": __version__,
        "protocol_version": SWARM_PROTOCOL_VERSION,
        "fsm_state": cur_fsm,
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
        "pending_solidify": pending,
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
        "supervision": sup,
        "bench_pack_gate": bench_gate,
        "working_session": _working_snapshot(),
        "bound_paths": describe_bound_paths(),
        "next_action": next_act,
        "hint": prose,
    }


def swarm_doctor() -> dict[str, Any]:
    """Read-only open-box summary (never runs ``--fix``)."""
    from evolver.ops.open_box import SOFT_GAP_ERRORS, doctor

    report = doctor(fix=False)
    checks = [
        {
            "id": c.get("id"),
            "ok": bool(c.get("ok")),
            "error": c.get("error"),
            "severity": (
                "ok" if c.get("ok") else ("soft" if c.get("error") in SOFT_GAP_ERRORS else "hard")
            ),
        }
        for c in (report.get("checks") or [])
    ]
    return {
        "ok": bool(report.get("ok")),
        "fsm_state": fsm_state(),
        "soft_continue": bool(report.get("soft_continue")),
        "loop_ready": bool(report.get("loop_ready")),
        "read_only": True,
        "checks": checks,
        "warnings": list(report.get("recommendations") or []),
        "blockers": list(report.get("blockers") or []),
        "repo_root": report.get("repo_root"),
        "workspace_id": report.get("workspace_id"),
    }


def _extract_host_account(response_text: str) -> str:
    prose = re.sub(r"```[a-zA-Z]*\s*\n.*?```", "", response_text, flags=re.DOTALL)
    return prose.strip()[:2000]


def swarm_distill(
    response_text: str,
    dry_run: bool = False,
    *,
    strict_transferable: bool = False,
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Distill structured Gene/Capsule blocks and record host clues."""
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    try:
        from evolver.gep.distill import DISTILL_FORMAT_HINT, distill_text, install_distilled
    except ImportError as exc:
        return _stale_import_error(exc)

    if not response_text.strip():
        return {"ok": False, "error": "empty_response", "next_action": "evolve_settle"}
    try:
        distilled = distill_text(response_text)
        install = install_distilled(
            distilled,
            dry_run=dry_run,
            attribution=attribution,
            strict_transferable=strict_transferable,
        )
    except ImportError as exc:
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
        "next_action": "evolve_settle",
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
    elif not dry_run:
        gene_ids = [str(g.get("id")) for g in distilled.get("genes") or [] if g.get("id")]
        if gene_ids:
            from evolver.gep.solidify import record_landed_gene_ids

            record_landed_gene_ids(gene_ids)
    if not dry_run:
        account = _extract_host_account(response_text)
        if account:
            from evolver.gep import episode_clue

            result["clue"] = episode_clue.append_clue(account, source="host_distill")
    return result


def _hypothesis_payload(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    stored = dict(payload)
    if run_id and run_id != "unknown":
        stored.setdefault("run_id", run_id)
    return stored


def _record_host_hypothesis(payload: dict[str, Any]) -> dict[str, Any]:
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
            "next_action": "evolve_begin",
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
            "next_action": "evolve_begin",
        }
    return {"ok": True, "hypothesis_path": str(path), "next_action": "evolve_settle"}


def swarm_hypothesis(
    hypothesis: dict[str, Any] | str,
    agent_name: str = "host-agent",
) -> dict[str, Any]:
    """Record a round hypothesis (accepts either a plain sentence or §5.3 dict)."""
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    run_id = _pending_solidify_meta()["run_id"]
    if isinstance(hypothesis, str):
        if not hypothesis.strip():
            return {
                "ok": False,
                "error": "hypothesis_rejected",
                "message": "hypothesis must be non-empty",
                "next_action": "evolve_begin",
            }
        payload = _synthesize_internal_hypothesis(hypothesis, run_id=run_id or "run_manual")
    elif isinstance(hypothesis, dict):
        payload = _hypothesis_payload(hypothesis, run_id)
    else:
        return {
            "ok": False,
            "error": "hypothesis_rejected",
            "message": "hypothesis must be a string or JSON object",
            "next_action": "evolve_begin",
        }
    result = _record_host_hypothesis(payload)
    if result.get("ok"):
        result["agent_name"] = agent_name
    return result


def swarm_propose(
    proposal: dict[str, Any],
    agent_name: str = "host-agent",
    hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a mechanical GeneProposal with anchor validation."""
    blocked = _checkpoint_block()
    if blocked is not None:
        return blocked
    from evolver.gep.instance_lock import instance_lock_ctx
    from evolver.gep.paths import get_workspace_root
    from evolver.gep.proposal import apply_proposal, compose_proposals, parse_proposal

    with instance_lock_ctx(blocking=False, timeout=0) as lock_ok:
        if not lock_ok:
            return {
                "ok": False,
                "error": "instance_lock_held",
                "agent_name": agent_name,
                "next_action": "stop_and_report",
            }
        workspace_root = get_workspace_root()
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
                    list(apply_rep.get("files_changed") or [])
                    if isinstance(apply_rep, dict)
                    else []
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
                "next_action": "evolve_settle",
            }

        integrity_report: dict[str, Any] | None = None
        if (
            isinstance(proposal, dict)
            and proposal.get("check_component_integrity")
            and files_changed
        ):
            from evolver.gep.policy_check import validate_harness_component_integrity

            raw_integrity = validate_harness_component_integrity(workspace_root, files_changed)
            integrity_report = {
                "ok": bool(raw_integrity.get("ok")),
                "violations": [
                    v.to_dict() if hasattr(v, "to_dict") else v
                    for v in (raw_integrity.get("violations") or [])
                ],
            }

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
            "next_action": "evolve_begin" if decision == "keep_base" else "evolve_settle",
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
    """Run the solidify gate, settle in-band blackbox, and record boundary episode."""
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
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep import supervision
    from evolver.gep.blackbox import load_active_blackbox, settle_blackbox
    from evolver.gep.paths import get_repo_root, get_workspace_root
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
            "next_action": "evolve_begin",
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
            "next_action": "evolve_begin",
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
            result["next_action"] = (
                "await_human_approval" if status == "pending" else "evolve_begin"
            )
        elif err == "supervision_paused":
            result["next_action"] = "await_supervisor_resume"
        elif err == "supervision_veto":
            result["next_action"] = "evolve_begin"
        if not result.get("ok") and "failure_mode" not in result:
            from evolver.gep.solidify import classify_failure_mode

            details = result.get("details")
            if err == "validation_failed" and isinstance(details, dict):
                mode = classify_failure_mode(validation=details.get("validation_result"))
            else:
                mode = {"mode": "hard", "reasonClass": err or "unknown", "retryable": False}
            result["failure_mode"] = mode
            result.setdefault(
                "next_action", "evolve_begin" if mode.get("retryable") else "stop_and_report"
            )

    # P1-2: Settle cycle-boundary blackbox BEFORE episode_record.record_round so
    # gates.blackbox is folded into the content-addressed episode atomically.
    if isinstance(result, dict) and result.get("event_id"):
        event_id_str = str(result["event_id"])
        active_bb = load_active_blackbox()
        if active_bb is not None:
            with contextlib.suppress(Exception):
                from evolver.gep.evidence import load_evidence

                cwd = (get_repo_root(_quiet=True) or get_workspace_root()).resolve()
                scene = load_evidence(run_id, event_id_str)
                val_res = (
                    scene.get("validation_result")
                    if isinstance(scene, dict) and isinstance(scene.get("validation_result"), dict)
                    else None
                )
                bb_entry = settle_blackbox(
                    cwd,
                    run_id=run_id,
                    event_id=event_id_str,
                    outcome_ok=bool(result.get("ok")),
                    outcome_label=str(
                        result.get("outcome") or ("promoted" if result.get("ok") else "failed")
                    ),
                    validation_result=val_res,
                    clear_active=not _pending_solidify_state(),
                )
                result["blackbox"] = {
                    "wall_time_ms": bb_entry.get("wall_time_ms"),
                    "lens_calls_count": bb_entry.get("lens_calls_count"),
                    "ast_delta": bb_entry.get("ast_delta"),
                    "validation": bb_entry.get("validation"),
                }

        from evolver.gep import episode_record

        try:
            ep_res = episode_record.record_round(event_id=event_id_str, run_id=str(run_id or ""))
            result["episode"] = ep_res
            if ep_res.get("id"):
                result["episode_id"] = str(ep_res["id"])
                if isinstance(result.get("experience_written"), dict):
                    result["experience_written"]["episodes"] = [str(ep_res["id"])]
        except Exception as exc:
            result["episode"] = {"ok": False, "error": f"episode_record_failed: {exc}"}

        # P2-2: Zero-human OperatorGene synthesis on helped, all-green rounds.
        if result.get("ok") is True and event_id_str:
            with contextlib.suppress(Exception):
                from evolver.gep.evidence import load_evidence
                from evolver.gep.git_ops import capture_diff_snapshot
                from evolver.gep.operator_synthesizer import synthesize_operator_from_fix

                ep_id_str = str(result.get("episode_id") or "")
                ep_body = episode_record.load_episode(ep_id_str) if ep_id_str else None
                ep_gates = ep_body.get("gates") if isinstance(ep_body, dict) else {}
                ep_attr = (
                    ep_gates.get("attribution")
                    if isinstance(ep_gates, dict) and isinstance(ep_gates.get("attribution"), dict)
                    else None
                )
                cwd = (get_repo_root(_quiet=True) or get_workspace_root()).resolve()
                scene = load_evidence(str(run_id or ""), event_id_str)
                ev_obj = scene.get("event") if isinstance(scene, dict) else {}
                diff_txt = (
                    str(ev_obj.get("diff_snapshot") or "") if isinstance(ev_obj, dict) else ""
                )
                if not diff_txt:
                    diff_txt = capture_diff_snapshot(cwd, max_chars=8000)
                synth = synthesize_operator_from_fix(
                    cwd=cwd,
                    run_id=str(run_id or ""),
                    signals=list(ev_obj.get("signals") or []) if isinstance(ev_obj, dict) else [],
                    diff_text=diff_txt,
                    ast_delta=(
                        (result.get("blackbox") or {}).get("ast_delta")
                        if isinstance(result.get("blackbox"), dict)
                        else None
                    ),
                    attribution=ep_attr,
                    validation_ok=True,
                )
                if synth.get("ok"):
                    result["operator_synthesis"] = synth
                    if isinstance(result.get("experience_written"), dict) and synth.get(
                        "operator_id"
                    ):
                        result["experience_written"].setdefault("operators", []).append(
                            str(synth["operator_id"])
                        )

    if isinstance(result, dict):
        with contextlib.suppress(Exception):
            from evolver.gep.compact_gate import note_outcome

            note_outcome(bool(result.get("ok")))
        with contextlib.suppress(Exception):
            from evolver.gep.index_db import sync_index_db

            sync_index_db()
        with contextlib.suppress(Exception):
            from evolver.gep.asset_store import read_all_events
            from evolver.gep.gene_lifecycle import evaluate_and_apply

            evaluate_and_apply(read_all_events())
    return result


def swarm_checkpoint_working(content: str) -> dict[str, Any]:
    """Write ``WORKING_SESSION.md`` and clear a pending compaction marker."""
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
    }


def swarm_report(
    category: str | None = None,
    description: str | None = None,
    resolution: str | None = None,
    no_write: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    from evolver.config import SWARM_TICK_LOG_MAX_CHARS
    from evolver.gep.autopoiesis import run_self_report_cli

    write_free = bool(no_write or dry_run)
    with _capture_stdout() as capture:
        try:
            data = run_self_report_cli(
                category=category,
                description=description,
                resolution=resolution,
                no_write=write_free,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"self_report_failed: {exc}",
                "engine_log": _tail(capture.getvalue(), SWARM_TICK_LOG_MAX_CHARS),
                "wrote": False,
                "written": [],
                "no_write": write_free,
                "dry_run": write_free,
            }
    written = data.get("written") if isinstance(data, dict) else None
    return {
        "ok": True,
        "wrote": bool(data.get("wrote")) if isinstance(data, dict) else not write_free,
        "written": list(written) if isinstance(written, list) else [],
        "no_write": write_free,
        "dry_run": write_free,
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
        "at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    with contextlib.suppress(OSError):
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
    from evolver.gep.workflow import WorkflowEngine, load_spec, load_template

    if bool(file) == bool(template):
        return {"ok": False, "error": "exactly one of file|template is required"}
    try:
        spec = load_spec(Path(file)) if file is not None else load_template(template or "")
    except (OSError, FileNotFoundError) as exc:
        return {"ok": False, "error": f"spec_unreadable:{exc}"}
    if workflow_id:
        spec["id"] = workflow_id
    engine = WorkflowEngine()
    try:
        state = engine.create(spec)
        state = engine.run(state)
    except Exception as exc:
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


def swarm_workflow_status(workflow_id: str) -> dict[str, Any]:
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
    """Single-entry CLI host round inspector (``evolver internal round --host``)."""
    _ = include_prompt
    status = evolve_status(project=project)
    return {
        "ok": True,
        "mode": "host_round",
        "agent_name": agent_name,
        "fsm_state": status.get("fsm_state"),
        "repo_root": status.get("repo_root"),
        "workspace_id": status.get("workspace_id"),
        "state_root": status.get("state_dir"),
        "bound_paths": status.get("bound_paths"),
        "next_action": status.get("next_action"),
        "allowed_tools": status.get("allowed_tools"),
        "status": status,
    }


__all__ = [
    "SWARM_PROTOCOL_VERSION",
    "bind_project_directory",
    "build_instrument_prompt",
    "describe_bound_paths",
    "evolve_begin",
    "evolve_run_lens",
    "evolve_settle",
    "evolve_status",
    "fsm_state",
    "host_relay_blocked",
    "swarm_checkpoint_working",
    "swarm_distill",
    "swarm_doctor",
    "swarm_feedback",
    "swarm_hook_event",
    "swarm_hooks",
    "swarm_host_round",
    "swarm_hypothesis",
    "swarm_propose",
    "swarm_report",
    "swarm_skills",
    "swarm_solidify",
    "swarm_status",
    "swarm_supervise",
    "swarm_workflow_act",
    "swarm_workflow_run",
    "swarm_workflow_status",
]
