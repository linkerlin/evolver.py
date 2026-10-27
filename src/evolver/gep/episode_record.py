"""Episode record (经验即证据 §5.1) - the runtime-held record of one self-improvement round.

SelfSearch 的 ``e_k`` (轨迹 + 代码 diff + 检查结果, 由 fixed runtime 记录、写后不可变、
只读交给下一代 improver) 在本仓的引擎侧一半。规则四条:

1. **一轮只记一次**: 同内容重记幂等 (``already_stored``), 同一轮异内容拒写
   (:class:`EpisodeConflictError`) - 被进化对象改不了自己的历史。
2. **内容寻址**: ``sha256:`` id, 与 :mod:`evolver.gep.library` 同一纪律。
3. **只收引擎自记** (:data:`ENGINE_SIDE_FIELDS`): 选中基因、diff、检查结果、门裁决。
   宿主上报的 account / 工具动作是**线索层**, 走提示词的线索块, 不入此库
   (白名单之外的键一律拒)。
4. **写入口在周期边界**: ``solidify.py`` / ``evolve/`` / ``bench/`` 不得引用
   :func:`record_episode` 一族 (调用图钉, 测试钉住) - 变异路径写不进自己的记录。

存储在仓外 ``<EVOLUTION_DIR>/episodes/``: ``index.json`` 汇总 (一轮一行) +
``<id>/episode.json`` 正文。与 :mod:`evolver.gep.evidence` 的关系: evidence 是原始现场
(按 run_id/kind、永不覆写), episode 是它的**有界、可引用视图** + 身份 id + 索引;
不复制原始现场, 不另起账本。``recorded_at`` 取事件时间戳而非墙上时钟 - 重推导同内容,
否则幂等无从谈起。

失败结算与成功结算同一形状: 选中基因、diff、检查、门裁决。现场由 solidify
在回滚前写下, episode 仍只在周期边界记。过程态 (没有候选被裁决) 不入此库。
Node.js 无等价物 (本阶段新机制)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, TypeGuard

from evolver.gep.asset_store import atomic_write_json, with_file_lock
from evolver.gep.content_hash import canonicalize, compute_asset_id
from evolver.gep.paths import get_evolution_dir

EPISODES_DIRNAME: Final = "episodes"
INDEX_FILENAME: Final = "index.json"
EPISODE_FILENAME: Final = "episode.json"
EPISODE_FORMAT: Final = "evolver.episode_record.v0"
EPISODE_INDEX_FORMAT: Final = "evolver.episode_index.v0"
INSPECT_CALLS_FILENAME: Final = "inspect_calls.jsonl"

#: A record is a citation, not a transcript: bounded so the next improver can
#: read it whole. The full scene stays in ``gep/evidence``.
MAX_DIFF_CHARS: Final = 4000
MAX_CHECKS: Final = 20
MAX_CHECK_OUTPUT_CHARS: Final = 400
MAX_RECORD_CHARS: Final = 64_000
#: One inspect call may request this many slices. Each slice is capped so a
#: zoom cannot paste the whole scene back into context.
MAX_INSPECT_VIEWS: Final = 8
MAX_INSPECT_VIEW_CHARS: Final = 2_000
MAX_INSPECT_QUESTION_CHARS: Final = 500
MAX_INSPECT_LIMIT_LINES: Final = 200

#: The record holds what the engine observed. Host-reported material has its
#: own channel (the prompt's clue block) and must not enter here.
ENGINE_SIDE_FIELDS: Final = (
    "format",
    "run_id",
    "event_id",
    "recorded_at",
    "gene",
    "diff",
    "checks",
    "gates",
    "outcome",
    "scene_index",
)
HOST_SIDE_KEYS: Final = (
    "account",
    "tool_actions",
    "tool_results",
    "host_report",
    "host_claims",
    "textual_gradient",
    "transcript",
    "trajectory",
    "reasoning",
)

_SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9._-]+$")

#: Harness2 (arXiv:2610.14224v1 §3.2) four-way component attribution verdicts.
#: Multi-component edits without isolated execution evidence default to
#: ``confounded`` and are excluded from durable experience distillation.
ATTRIBUTION_VERDICTS: Final[tuple[str, ...]] = (
    "helped",
    "hurt",
    "no_observed_effect",
    "confounded",
)


class EpisodeConflictError(RuntimeError):
    """Raised when a round is already recorded with different content.

    An episode is written once: two different histories must never share a
    round, because the id is what the next improver cites.
    """


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def episodes_dir() -> Path:
    return get_evolution_dir() / EPISODES_DIRNAME


def index_path() -> Path:
    return episodes_dir() / INDEX_FILENAME


def episode_id(payload: dict[str, Any]) -> str:
    """Content address of one episode — same bytes, same id, always."""
    return compute_asset_id(payload)


def episode_path(ep_id: str) -> Path:
    """Path of one episode body.

    The id is ``sha256:<hex>`` and Windows refuses a colon in a path
    component, so the directory name escapes it — a storage detail, not a
    second identity (same as ``gep/library.py``).
    """
    return episodes_dir() / str(ep_id).replace(":", "_", 1) / EPISODE_FILENAME


def round_key(payload: dict[str, Any]) -> str:
    """Identity of the round one episode records (run id first, event as fallback)."""
    run_id = str(payload.get("run_id") or "")
    event_id = str(payload.get("event_id") or "")
    return f"{run_id or '-'}#{event_id or '-'}"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load_index() -> dict[str, Any]:
    """The round ledger. A corrupt ledger is never silently restarted —
    reopening it would fork history, so it fails loudly instead."""
    path = index_path()
    if not path.exists():
        return {"format": EPISODE_INDEX_FORMAT, "episodes": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EpisodeConflictError(f"episode index is unreadable: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("episodes"), list):
        raise EpisodeConflictError(f"episode index is malformed: {path}")
    return payload


def list_episodes() -> list[dict[str, Any]]:
    """Index entries in recording order — what ``evolver episode list`` prints."""
    return [row for row in load_index().get("episodes", []) if isinstance(row, dict)]


def load_episode(ep_id: str) -> dict[str, Any] | None:
    """One episode body by id. A read — never touches any pointer."""
    path = episode_path(ep_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def render_episode_block(body: dict[str, Any], *, ep_id: str = "", max_chars: int = 2000) -> str:
    """Render one episode as paste-into-prompt context (bounded, truncation marked).

    The next improver reads the previous round whole — that is the point of the
    record. The block is a summary, not the body: the body stays content-
    addressed in the store, cited by id.
    """
    raw_gene = body.get("gene")
    gene: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
    raw_outcome = body.get("outcome")
    outcome: dict[str, Any] = raw_outcome if isinstance(raw_outcome, dict) else {}
    raw_gates = body.get("gates")
    gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
    raw_acceptance = gates.get("acceptance")
    acceptance: dict[str, Any] = raw_acceptance if isinstance(raw_acceptance, dict) else {}
    raw_checks = body.get("checks")
    checks: list[Any] = raw_checks if isinstance(raw_checks, list) else []
    ok_count = sum(1 for c in checks if isinstance(c, dict) and c.get("ok"))
    diff = _clip(body.get("diff"), max(1, max_chars // 4))
    lines = [
        "## Previous Episode (read-only experience)",
        f"- episode id: `{ep_id or body.get('event_id') or 'unknown'}`",
        f"- run: {body.get('run_id') or 'unknown'}  gene: {gene.get('id') or 'unknown'}  "
        f"outcome: {outcome.get('status') or 'unknown'}  score: {outcome.get('score')}",
        f"- checks: {ok_count}/{len(checks)} ok",
        f"- gates: acceptance={acceptance.get('accepted') if acceptance else 'none'}",
        *_prediction_delta_line(gates),
        *_attribution_line(gates),
        *_behavioral_contrast_line(gates),
        *_inspect_anchors(body),
        "```diff",
        diff or "(no diff)",
        "```",
    ]
    block = "\n".join(lines)
    return block if len(block) <= max_chars else block[:max_chars] + "\n... (truncated)"


def ceiling_tie_note(body: dict[str, Any]) -> str:
    """One line when a tied score against a perfect baseline resolved nothing.

    The summary above shows status and score. A flat pack rejection at
    baseline 1.0 did not test the hypothesis: the gate had no headroom.
    Kept out of :func:`render_episode_block` because the ablation record arm
    shares that text. Every other body, including a missing field, returns "".
    """
    outcome = body.get("outcome")
    if not isinstance(outcome, dict):
        return ""
    if outcome.get("error") != "bench_pack_rejected" or outcome.get("pack_reason") != "flat":
        return ""
    gates = body.get("gates")
    bench = gates.get("bench_pack") if isinstance(gates, dict) else None
    baseline = bench.get("baseline") if isinstance(bench, dict) else None
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)):
        return ""
    if float(baseline) != 1.0:
        return ""
    return "- 基线已满分，分数持平，这一轮测不出假说对错。"


def attribution_note(body: dict[str, Any]) -> str:
    """One line summarizing Harness2 4-way component attribution for dispatch.

    Kept separate from :func:`render_episode_block` for episodes that did not
    explicitly store ``gates.attribution`` so the ablation record arm's prompt
    rendering stays byte-identical on historical episodes. Returns ``""`` when
    no files or target hooks were touched.
    """
    if not isinstance(body, dict):
        return ""
    raw_gates = body.get("gates")
    gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
    existing = gates.get("attribution")
    if isinstance(existing, dict):
        lines = _attribution_line(gates)
        return lines[0] if lines else ""
    raw_gene = body.get("gene")
    gene: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
    raw_checks = body.get("checks")
    checks: list[dict[str, Any]] = (
        [c for c in raw_checks if isinstance(c, dict)] if isinstance(raw_checks, list) else []
    )
    raw_outcome = body.get("outcome")
    outcome: dict[str, Any] | None = raw_outcome if isinstance(raw_outcome, dict) else None
    pred_delta = (
        gates.get("prediction_delta") if isinstance(gates.get("prediction_delta"), dict) else None
    )
    computed = compute_component_attribution(
        _text(body.get("diff")),
        checks,
        outcome=outcome,
        prediction_delta=pred_delta,
        target_hook=_text(gene.get("target_hook")) or None,
    )
    if int(computed.get("touched_count") or 0) <= 0:
        return ""
    lines = _attribution_line({"attribution": computed})
    return lines[0] if lines else ""


def behavioral_contrast_note(
    body: dict[str, Any],
    previous_body: dict[str, Any] | None = None,
) -> str:
    """One line summarizing Harness2 check transitions across consecutive episodes.

    Kept separate from :func:`render_episode_block` for historical episodes that
    did not store ``gates.behavioral_contrast`` so the ablation record arm stays
    byte-identical. Emits a line when ``gates.behavioral_contrast`` is already
    present, or when comparing against ``previous_body`` reveals newly passed or
    regressed checks (or a non-delivering empty round).
    """
    if not isinstance(body, dict):
        return ""
    raw_gates = body.get("gates")
    gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
    existing = gates.get("behavioral_contrast")
    if isinstance(existing, dict):
        lines = _behavioral_contrast_line(gates)
        return lines[0] if lines else ""
    raw_checks = body.get("checks")
    cur_checks: list[dict[str, Any]] = (
        [c for c in raw_checks if isinstance(c, dict)] if isinstance(raw_checks, list) else []
    )
    prev_checks: list[dict[str, Any]] | None = None
    if isinstance(previous_body, dict):
        raw_prev = previous_body.get("checks")
        if isinstance(raw_prev, list):
            prev_checks = [c for c in raw_prev if isinstance(c, dict)]
    computed = compute_behavioral_contrast(
        cur_checks,
        prev_checks,
        diff_text=_text(body.get("diff")),
    )
    trans = computed.get("check_transitions") or {}
    newly_passed = trans.get("newly_passed") or []
    regressed = trans.get("regressed") or []
    non_delivering = bool(computed.get("non_delivering"))
    if not newly_passed and not regressed and not non_delivering:
        return ""
    lines = _behavioral_contrast_line({"behavioral_contrast": computed})
    return lines[0] if lines else ""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_episode(scene: dict[str, Any]) -> dict[str, Any]:
    """Derive the bounded, citable view from the engine's own scene.

    ``scene`` is the immutable evidence payload written at settlement
    (``{"event", "validation_result", "fitness_verdict", "gate"}``). Everything
    taken from it is engine-observed; anything else is dropped rather than
    copied — the record is a view, not a transcript.
    """
    if not isinstance(scene, dict):
        raise ValueError("episode scene must be a JSON object")
    raw_event = scene.get("event")
    event: dict[str, Any] = raw_event if isinstance(raw_event, dict) else {}
    raw_mutation = event.get("mutation")
    mutation: dict[str, Any] = raw_mutation if isinstance(raw_mutation, dict) else {}
    raw_outcome = event.get("outcome")
    outcome: dict[str, Any] = raw_outcome if isinstance(raw_outcome, dict) else {}
    raw_diff = _text(event.get("diff_snapshot"))
    stored_diff = _clip(raw_diff, MAX_DIFF_CHARS)
    checks, check_index = _bounded_checks(scene.get("validation_result"))
    body: dict[str, Any] = {
        "format": EPISODE_FORMAT,
        "run_id": _text(event.get("run_id")),
        "event_id": _text(event.get("id")),
        # Event timestamp, not wall clock: re-deriving the same scene must give
        # the same bytes, or idempotent re-recording cannot hold.
        "recorded_at": _text(event.get("timestamp")),
        "gene": {
            "id": _text(event.get("gene_id")),
            "mutation_id": _text(mutation.get("id")),
            "category": _text(mutation.get("category")),
        },
        "diff": stored_diff,
        "checks": checks,
        "gates": _bounded_gates(scene.get("gate"), event),
        "outcome": outcome,
        "scene_index": {
            "diff_chars": len(raw_diff),
            "diff_stored_chars": len(stored_diff),
            "checks": check_index,
        },
    }
    return validate_episode(body)


def _bounded_checks(validation: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results = validation.get("results") if isinstance(validation, dict) else None
    if not isinstance(results, list):
        return [], []
    checks: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for entry in results[:MAX_CHECKS]:
        if not isinstance(entry, dict):
            continue
        stdout_raw = _text(entry.get("stdout"))
        stderr_raw = _text(entry.get("stderr"))
        stdout = _clip(stdout_raw, MAX_CHECK_OUTPUT_CHARS)
        stderr = _clip(stderr_raw, MAX_CHECK_OUTPUT_CHARS)
        command = _text(entry.get("command"))
        checks.append(
            {
                "command": command,
                "ok": bool(entry.get("ok")),
                "duration_ms": entry.get("duration_ms")
                if isinstance(entry.get("duration_ms"), (int, float))
                else None,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        index.append(
            {
                "command": command,
                "stdout_chars": len(stdout_raw),
                "stdout_stored_chars": len(stdout),
                "stderr_chars": len(stderr_raw),
                "stderr_stored_chars": len(stderr),
            }
        )
    return checks, index


def _bounded_gates(gate: Any, event: dict[str, Any]) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    if isinstance(gate, dict):
        gates["acceptance"] = gate
    for key, alias in (
        ("fitness_gate", "fitness"),
        ("bench_pack", "bench_pack"),
        ("anchor_result", "anchor"),
    ):
        value = event.get(key)
        if isinstance(value, dict):
            gates[alias] = value
    return gates


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate_episode(payload: dict[str, Any]) -> dict[str, Any]:
    """Whitelist check: engine-side fields only, an identity, bounded size.

    Host-side keys are refused with their own error — the clue layer has a
    channel of its own, and an episode that silently absorbed host claims
    would grade the host's carefulness again.
    """
    if not isinstance(payload, dict):
        raise ValueError("episode payload must be a JSON object")
    for key in payload:
        if key in HOST_SIDE_KEYS:
            raise ValueError(f"host-reported field refused in an episode record: {key!r}")
        if key not in ENGINE_SIDE_FIELDS:
            raise ValueError(f"unknown episode field: {key!r}")
    if not str(payload.get("run_id") or "") and not str(payload.get("event_id") or ""):
        raise ValueError("episode record needs a run_id or an event_id")
    if not isinstance(payload.get("checks", []), list):
        raise ValueError("episode checks must be a list")
    if payload.get("gates") is not None and not isinstance(payload.get("gates"), dict):
        raise ValueError("episode gates must be a JSON object")
    if len(canonicalize(payload)) > MAX_RECORD_CHARS:
        raise ValueError(f"episode record exceeds {MAX_RECORD_CHARS} chars — trim the scene view")
    return dict(payload)


# ---------------------------------------------------------------------------
# Write (周期边界调用; solidify.py / evolve/ / bench/ 不得引用)
# ---------------------------------------------------------------------------


def _seal_value(value: Any) -> Any:
    """Recursively redact strong val secrets out of a record body's strings.

    The record is engine-side and should never carry val wording. If a stray
    secret appears (a host edit that quoted the exam), the string is replaced
    with the seal placeholder — the round's history is kept, the secret is
    not. Weak (short) strings are never decided on: redaction only fires on
    strong hits, so ordinary prose is untouched.
    """
    if isinstance(value, str):
        from evolver.gep.val_seal import redact

        scrubbed, _report = redact(value, where="episode_record")
        return scrubbed
    if isinstance(value, list):
        return [_seal_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _seal_value(item) for key, item in value.items()}
    return value


def _attach_gene_metadata(body: dict[str, Any]) -> dict[str, Any]:
    """Attach target_hook/mechanism_family from the gene library.

    The record is self-contained for usage recomputation (经验即证据 §5.4):
    the meta-report can tell an improver-tool round from a mutation round
    without a second lookup. Best-effort — an unknown gene id leaves the
    fields absent, and the meta-report falls back to its own lookup.
    """
    gene = body.get("gene")
    if not isinstance(gene, dict):
        return body
    gene = dict(gene)  # copy — never mutate the caller's payload
    body["gene"] = gene
    gene_id = str(gene.get("id") or "")
    if not gene_id:
        return body
    from evolver.gep.asset_store import load_genes

    for candidate in load_genes():
        if str(candidate.get("id")) == gene_id:
            gene["target_hook"] = candidate.get("target_hook")
            gene["mechanism_family"] = candidate.get("mechanism_family")
            break
    return body


def record_episode(payload: dict[str, Any]) -> dict[str, Any]:
    """Store one episode under its content address and index the round.

    Idempotent for the same content (same round, same bytes). A different
    body for an already-recorded round raises :class:`EpisodeConflictError` —
    a round is history, and history is not rewritten. The body is val-sealed
    and gene-attributed before it is stored: a record that carried exam
    wording would be a leak with a content address, and a record that could
    not say which gene it applied could not answer "was it an improver tool?".
    """
    body = _attach_gene_metadata(_seal_value(validate_episode(payload)))
    ep_id = episode_id(body)
    key = round_key(body)
    target = episode_path(ep_id)
    with with_file_lock(target_path=episodes_dir()):
        index = load_index()
        entries: list[Any] = index.setdefault("episodes", [])
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("round_key") != key:
                continue
            if entry.get("id") != ep_id:
                raise EpisodeConflictError(
                    f"round {key} is already recorded as {entry.get('id')} - written once"
                )
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(target, body)
            return {
                "ok": True,
                "reason": "already_stored",
                "id": ep_id,
                "round_key": key,
                "path": str(target),
            }
        if target.exists():
            existing = load_episode(ep_id)
            if canonicalize(existing) != canonicalize(body):
                raise EpisodeConflictError(
                    f"episode {ep_id} exists with different content - records never overwrite"
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(target, body)
        entries.append(_index_entry(body, ep_id, key))
        atomic_write_json(index_path(), index)
    return {"ok": True, "reason": "stored", "id": ep_id, "round_key": key, "path": str(target)}


def record_round(event_id: str, run_id: str = "") -> dict[str, Any]:
    """Record the round that produced ``event_id`` from its immutable scene.

    The cycle boundary (CLI / MCP) calls this after a settled round. The
    scene is looked up in ``gep.evidence`` — the record is derived from what
    the engine already stored, never from what the host reports. When the
    host declared ``expected_outcome`` beforehand, the engine writes
    ``gates.prediction_delta`` from the checks it actually observed.
    """
    scene = _find_scene(event_id, run_id)
    if scene is None:
        return {"ok": False, "error": "scene_missing", "event_id": event_id}
    return record_episode(_attach_prediction_delta(build_episode(scene)))


def find_episode_id_for_run(run_id: str) -> str | None:
    """Latest episode id whose index row cites ``run_id``. Read-only."""
    if not run_id:
        return None
    for row in reversed(list_episodes()):
        if str(row.get("run_id") or "") == run_id and row.get("id"):
            return str(row["id"])
    return None


def inspect_calls_path() -> Path:
    return episodes_dir() / INSPECT_CALLS_FILENAME


def note_inspect_call(result: dict[str, Any]) -> None:
    """Append one successful host inspect to a side log; episodes stay untouched.

    A row names the episode, its cycle run, the paired session running at the
    time (the join key for the RERE panel), and the view kinds. The question
    text is not logged.
    """
    if not result.get("ok"):
        return
    from datetime import UTC, datetime

    from evolver.gep.evolution_session import active_session

    session = active_session()
    views = result.get("views")
    row = {
        "at": datetime.now(UTC).isoformat(),
        "episode_id": result.get("source_episode_id"),
        "run_id": result.get("run_id"),
        "session_run_id": session.get("run_id") if session else None,
        "view_kinds": [str(view.get("kind")) for view in views or [] if isinstance(view, dict)],
    }
    path = inspect_calls_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_inspect_calls() -> list[dict[str, Any]]:
    """Rows of the inspect side log, oldest first. Unreadable lines are skipped."""
    path = inspect_calls_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def inspect_episode_scene(
    ep_id: str,
    *,
    question: str,
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Slice the lossless scene behind one episode. Read-only.

    The prompt carries a clipped view. This reads ``gep/evidence`` for the
    run and returns the requested line window, val-sealed. An empty question
    is refused: the host must say what it is looking for. The question is
    returned as a host clue and is not written into the episode.
    """
    asked = question.strip() if isinstance(question, str) else ""
    if not asked:
        return _inspect_error(
            "empty_question",
            "Pass a non-empty question describing what you expect to find in this slice.",
        )
    if len(asked) > MAX_INSPECT_QUESTION_CHARS:
        return _inspect_error(
            "question_too_long",
            f"question must be at most {MAX_INSPECT_QUESTION_CHARS} characters.",
        )
    if not isinstance(views, list) or not 1 <= len(views) <= MAX_INSPECT_VIEWS:
        return _inspect_error(
            "bad_views",
            f"views must be a list of 1 to {MAX_INSPECT_VIEWS} slice objects.",
        )
    body = load_episode(ep_id)
    if body is None:
        return _inspect_error("episode_not_found", f"episode not found: {ep_id}")
    run_id = str(body.get("run_id") or "")
    event_id = str(body.get("event_id") or "")
    scene = _load_scene(run_id, event_id)
    if scene is None:
        return _inspect_error(
            "scene_missing",
            "The episode cites no lossless scene. There is nothing further to zoom into.",
        )
    sliced: list[dict[str, Any]] = []
    for index, view in enumerate(views, start=1):
        try:
            sliced.append(_slice_view(scene, view, index))
        except ValueError as exc:
            return _inspect_error("bad_view", str(exc))
    from evolver.gep.val_seal import redact

    sealed_question, _report = redact(asked, where="episode_inspect")
    return {
        "ok": True,
        "source_episode_id": ep_id,
        "run_id": run_id,
        "current_state_unchanged": True,
        "question": {"text": sealed_question, "source": "host_query"},
        "views": sliced,
    }


def _find_scene(event_id: str, run_id: str = "") -> dict[str, Any] | None:
    """Locate one settlement scene by event id (and run id when known)."""
    from evolver.gep.evidence import load_evidence
    from evolver.gep.paths import get_gep_assets_dir

    if not event_id or not _SAFE_ID_RE.match(event_id):
        return None
    if run_id and _SAFE_ID_RE.match(run_id):
        scene = load_evidence(run_id, event_id)
        if isinstance(scene, dict):
            return scene
    root = get_gep_assets_dir() / "evidence"
    if not root.is_dir():
        return None
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not _SAFE_ID_RE.match(directory.name):
            continue
        scene = load_evidence(directory.name, event_id)
        if isinstance(scene, dict):
            return scene
    return None


def _index_entry(body: dict[str, Any], ep_id: str, key: str) -> dict[str, Any]:
    raw_outcome = body.get("outcome")
    outcome: dict[str, Any] = raw_outcome if isinstance(raw_outcome, dict) else {}
    raw_gene = body.get("gene")
    gene: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
    raw_gates = body.get("gates")
    gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
    raw_acceptance = gates.get("acceptance")
    acceptance: dict[str, Any] = raw_acceptance if isinstance(raw_acceptance, dict) else {}
    return {
        "id": ep_id,
        "round_key": key,
        "run_id": body.get("run_id"),
        "event_id": body.get("event_id"),
        "recorded_at": body.get("recorded_at"),
        "gene_id": gene.get("id"),
        "outcome_status": outcome.get("status"),
        "score": outcome.get("score"),
        "accepted": acceptance.get("accepted") if acceptance else None,
    }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _attach_prediction_delta(body: dict[str, Any]) -> dict[str, Any]:
    """Fold the engine's check-vs-expectation delta into ``gates`` when declared.

    Reads the record the gate consumed for this run; absent ``expected_outcome``
    leaves the body unchanged. The delta is computed here, at the cycle
    boundary, from the checks already in the episode — the host does not
    supply it.
    """
    from evolver.gep.hypothesis import compute_prediction_delta, load_consumed_hypothesis

    recorded = load_consumed_hypothesis(str(body.get("run_id") or ""))
    if recorded is None:
        return body
    expected = recorded.get("expected_outcome")
    if not isinstance(expected, dict):
        return body
    delta = compute_prediction_delta(expected, body.get("checks") or [])
    gates = dict(body.get("gates") or {})
    gates["prediction_delta"] = delta
    updated = dict(body)
    updated["gates"] = gates
    return updated


def _prediction_delta_line(gates: dict[str, Any]) -> list[str]:
    """Empty without a recorded delta, so older bodies render byte-identically."""
    delta = gates.get("prediction_delta")
    if not isinstance(delta, dict):
        return []
    unmet = json.dumps(delta.get("unmet_expectations") or [], ensure_ascii=False)
    unexpected = json.dumps(delta.get("unexpected_failures") or [], ensure_ascii=False)
    return [
        f"- prediction_delta: matched={delta.get('matched')} unmet={unmet} unexpected={unexpected}"
    ]


def _attribution_line(gates: dict[str, Any]) -> list[str]:
    """Empty without a recorded attribution, preserving byte-identical legacy rendering."""
    attr = gates.get("attribution")
    if not isinstance(attr, dict):
        return []
    status = attr.get("status") or "unknown"
    confounded = bool(attr.get("confounded"))
    eligible = bool(attr.get("eligible_for_experience"))
    return [
        f"- attribution: status={status} confounded={confounded} eligible_for_experience={eligible}"
    ]


def _behavioral_contrast_line(gates: dict[str, Any]) -> list[str]:
    """Empty without a recorded behavioral contrast, preserving legacy rendering."""
    contrast = gates.get("behavioral_contrast")
    if not isinstance(contrast, dict):
        return []
    transitions = contrast.get("check_transitions")
    trans_dict = transitions if isinstance(transitions, dict) else {}
    newly_passed = json.dumps(trans_dict.get("newly_passed") or [], ensure_ascii=False)
    regressed = json.dumps(trans_dict.get("regressed") or [], ensure_ascii=False)
    non_delivering = bool(contrast.get("non_delivering"))
    return [
        f"- behavioral_contrast: newly_passed={newly_passed} "
        f"regressed={regressed} non_delivering={non_delivering}"
    ]


_ENGINE_RUNTIME_PREFIXES: tuple[str, ...] = (
    "evolver/.config/",
    ".evolver/",
    ".evolver_settings/",
    ".evomap/",
    "memory/",
    "logs/",
)
_ENGINE_RUNTIME_FILES: frozenset[str] = frozenset(
    {
        ".gitignore",
        "LESSONS_LEARNED.md",
        "autopoiesis_rules.json",
    }
)


def _is_engine_runtime_artifact(path_str: str) -> bool:
    norm = path_str.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in _ENGINE_RUNTIME_FILES:
        return True
    return norm.startswith(_ENGINE_RUNTIME_PREFIXES)


def _extract_touched_files(diff_text: str) -> list[str]:
    """Extract ordered unique relative file paths modified in a unified diff."""
    text = _text(diff_text)
    if not text.strip():
        return []
    seen: list[str] = []

    def _add(raw_path: str) -> None:
        cleaned = raw_path.strip()
        if not cleaned or cleaned == "/dev/null":
            return
        if cleaned.startswith(("a/", "b/")) and len(cleaned) > 2:
            cleaned = cleaned[2:]
        if _is_engine_runtime_artifact(cleaned):
            return
        if cleaned and cleaned not in seen:
            seen.append(cleaned)

    for match in re.finditer(r"(?m)^diff --git a/(.+?) b/(.+)$", text):
        _add(match.group(2))
    if seen:
        return seen
    for match in re.finditer(r"(?m)^\+\+\+ (?:b/)?([^\t\r\n]+)$", text):
        _add(match.group(1))
    if seen:
        return seen
    for match in re.finditer(r"(?m)^--- (?:a/)?([^\t\r\n]+)$", text):
        _add(match.group(1))
    return seen


def _classify_component_group(path_str: str) -> str:
    """Map a touched relative path to a Harness2 component class."""
    norm = path_str.replace("\\", "/").strip("/")
    lower = norm.lower()
    base = norm.rsplit("/", 1)[-1]
    if "/skills/" in f"/{lower}" or base == "SKILL.md":
        return "skill"
    if "/scripts/" in f"/{lower}" or "/bin/" in f"/{lower}":
        return "script"
    if "/plugin/" in f"/{lower}" or "/hooks/" in f"/{lower}" or "compact_gate" in lower:
        return "hook_or_plugin"
    if base in {"AGENTS.md", "CLAUDE.md", "systemprompt.md", "guardrails.md", "prompt.py"}:
        return "always_on_prompt"
    if lower.startswith("tests/") or base.startswith("test_"):
        return "test"
    parts = norm.split("/")
    return f"code:{parts[0]}" if parts else "code"


def compute_component_attribution(
    diff_text: str,
    checks: list[dict[str, Any]],
    *,
    outcome: dict[str, Any] | None = None,
    prediction_delta: dict[str, Any] | None = None,
    target_hook: str | None = None,
) -> dict[str, Any]:
    """Harness2 (§3.2) four-way component attribution from engine-observed facts.

    Verdicts are strictly one of :data:`ATTRIBUTION_VERDICTS`:
    ``("helped", "hurt", "no_observed_effect", "confounded")``.
    Whenever a candidate modifies multiple components at once and no isolated
    execution separates them, the attribution is marked ``confounded`` and
    ``eligible_for_experience=False`` so multi-edit rounds never pollute the
    durable library.
    """
    touched_files = _extract_touched_files(diff_text)
    valid_checks = [c for c in checks if isinstance(c, dict)]
    any_check_failed = any(not bool(c.get("ok")) for c in valid_checks)
    all_checks_ok = bool(valid_checks) and all(bool(c.get("ok")) for c in valid_checks)
    out = outcome if isinstance(outcome, dict) else {}
    outcome_status = str(out.get("status") or "")
    pack_reason = str(out.get("pack_reason") or "")
    delta_unmatched = (
        isinstance(prediction_delta, dict) and prediction_delta.get("matched") is False
    )

    if not touched_files:
        hook_name = str(target_hook or "").strip()
        if not hook_name and not diff_text.strip():
            return {
                "status": "no_observed_effect",
                "confounded": False,
                "eligible_for_experience": False,
                "touched_count": 0,
                "components": [],
                "source": "engine",
            }
        touched_files = [hook_name or "<inline_diff>"]

    if len(touched_files) > 1:
        components = [
            {
                "component": path,
                "group": _classify_component_group(path),
                "verdict": "confounded",
                "reason": "multi_component_unisolated_edit",
            }
            for path in touched_files
        ]
        return {
            "status": "confounded",
            "confounded": True,
            "eligible_for_experience": False,
            "touched_count": len(touched_files),
            "components": components,
            "source": "engine",
        }

    single_path = touched_files[0]
    group = _classify_component_group(single_path)
    if (
        any_check_failed
        or pack_reason == "drop"
        or (outcome_status == "failed" and pack_reason != "flat" and bool(valid_checks))
    ):
        verdict = "hurt"
        reason = "check_or_outcome_regression"
    elif (
        pack_reason == "flat"
        or delta_unmatched
        or (not valid_checks and outcome_status != "success")
    ):
        verdict = "no_observed_effect"
        reason = "flat_or_unobserved_effect"
    elif all_checks_ok or outcome_status == "success":
        verdict = "helped"
        reason = "isolated_positive_check_signal"
    else:
        verdict = "no_observed_effect"
        reason = "flat_or_unobserved_effect"

    return {
        "status": verdict,
        "confounded": False,
        "eligible_for_experience": verdict == "helped",
        "touched_count": 1,
        "components": [
            {
                "component": single_path,
                "group": group,
                "verdict": verdict,
                "reason": reason,
            }
        ],
        "source": "engine",
    }


def attach_component_attribution(body: dict[str, Any]) -> dict[str, Any]:
    """Compute and attach ``gates.attribution`` onto an episode body copy."""
    raw_gates = body.get("gates")
    gates: dict[str, Any] = dict(raw_gates) if isinstance(raw_gates, dict) else {}
    raw_gene = body.get("gene")
    gene: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
    raw_checks = body.get("checks")
    checks: list[dict[str, Any]] = (
        [c for c in raw_checks if isinstance(c, dict)] if isinstance(raw_checks, list) else []
    )
    raw_outcome = body.get("outcome")
    outcome: dict[str, Any] | None = raw_outcome if isinstance(raw_outcome, dict) else None
    pred_delta = (
        gates.get("prediction_delta") if isinstance(gates.get("prediction_delta"), dict) else None
    )
    gates["attribution"] = compute_component_attribution(
        _text(body.get("diff")),
        checks,
        outcome=outcome,
        prediction_delta=pred_delta,
        target_hook=_text(gene.get("target_hook")) or None,
    )
    updated = dict(body)
    updated["gates"] = gates
    return updated


def compute_behavioral_contrast(
    current_checks: list[dict[str, Any]],
    baseline_checks: list[dict[str, Any]] | None = None,
    *,
    diff_text: str = "",
    tool_calls: int | None = None,
    tool_errors: int | None = None,
    baseline_tool_error_rate: float | None = None,
) -> dict[str, Any]:
    """Harness2 (§3.2 / Selector) behavioral contrast telemetry over check transitions."""
    cur_list = [c for c in current_checks if isinstance(c, dict)]
    base_map: dict[str, bool] = {}
    if isinstance(baseline_checks, list):
        for entry in baseline_checks:
            if isinstance(entry, dict) and entry.get("command"):
                base_map[str(entry["command"])] = bool(entry.get("ok"))

    newly_passed: list[str] = []
    regressed: list[str] = []
    persistent_failed: list[str] = []
    unchanged_passed: list[str] = []

    for entry in cur_list:
        cmd = str(entry.get("command") or "")
        if not cmd:
            continue
        cur_ok = bool(entry.get("ok"))
        prev_ok = base_map.get(cmd)
        if prev_ok is False and cur_ok is True:
            newly_passed.append(cmd)
        elif prev_ok is True and cur_ok is False:
            regressed.append(cmd)
        elif not cur_ok:
            persistent_failed.append(cmd)
        else:
            unchanged_passed.append(cmd)

    error_rate: float | None = None
    error_delta: float | None = None
    if _plain_int(tool_calls) and tool_calls > 0 and _plain_int(tool_errors) and tool_errors >= 0:
        error_rate = round(min(1.0, tool_errors / tool_calls), 4)
        if isinstance(baseline_tool_error_rate, (int, float)) and not isinstance(
            baseline_tool_error_rate, bool
        ):
            error_delta = round(error_rate - float(baseline_tool_error_rate), 4)

    ok_count = sum(1 for c in cur_list if bool(c.get("ok")))
    non_delivering = not bool(_text(diff_text).strip()) and ok_count == 0

    return {
        "check_transitions": {
            "newly_passed": newly_passed,
            "regressed": regressed,
            "persistent_failed": persistent_failed,
            "unchanged_passed": unchanged_passed,
        },
        "tool_error_rate": error_rate,
        "tool_error_delta": error_delta,
        "non_delivering": non_delivering,
        "source": "engine",
    }


def attach_behavioral_contrast(
    body: dict[str, Any],
    *,
    baseline_checks: list[dict[str, Any]] | None = None,
    tool_calls: int | None = None,
    tool_errors: int | None = None,
    baseline_tool_error_rate: float | None = None,
) -> dict[str, Any]:
    """Compute and attach ``gates.behavioral_contrast`` onto an episode body copy."""
    raw_gates = body.get("gates")
    gates: dict[str, Any] = dict(raw_gates) if isinstance(raw_gates, dict) else {}
    raw_checks = body.get("checks")
    checks: list[dict[str, Any]] = (
        [c for c in raw_checks if isinstance(c, dict)] if isinstance(raw_checks, list) else []
    )
    gates["behavioral_contrast"] = compute_behavioral_contrast(
        checks,
        baseline_checks,
        diff_text=_text(body.get("diff")),
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        baseline_tool_error_rate=baseline_tool_error_rate,
    )
    updated = dict(body)
    updated["gates"] = gates
    return updated


def _inspect_anchors(body: dict[str, Any]) -> list[str]:
    """One line per field the bounded view actually clipped."""
    index = body.get("scene_index")
    if not isinstance(index, dict):
        return []
    notes: list[str] = []
    original = index.get("diff_chars")
    stored = index.get("diff_stored_chars")
    if isinstance(original, int) and isinstance(stored, int) and original > stored:
        notes.append(
            f"- diff truncated at {stored}/{original} chars; call `episode_inspect` to zoom in"
        )
    raw_checks = index.get("checks")
    if isinstance(raw_checks, list):
        for meta in raw_checks:
            if not isinstance(meta, dict):
                continue
            command = str(meta.get("command") or "check")[:80]
            for total_key, stored_key, label in (
                ("stdout_chars", "stdout_stored_chars", "stdout"),
                ("stderr_chars", "stderr_stored_chars", "stderr"),
            ):
                total = meta.get(total_key)
                kept = meta.get(stored_key)
                if isinstance(total, int) and isinstance(kept, int) and total > kept:
                    notes.append(
                        f"- check `{command}` {label} truncated at {kept}/{total} chars; "
                        "call `episode_inspect` to zoom in"
                    )
    return notes


def _inspect_error(code: str, steer: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": code,
        "next_action": "revise_episode_inspect",
        "steer_message": steer,
        "current_state_unchanged": True,
    }


def _load_scene(run_id: str, event_id: str) -> dict[str, Any] | None:
    from evolver.gep.evidence import load_evidence

    if run_id and event_id and _SAFE_ID_RE.match(run_id) and _SAFE_ID_RE.match(event_id):
        scene = load_evidence(run_id, event_id)
        if isinstance(scene, dict):
            return scene
    if event_id:
        return _find_scene(event_id, run_id)
    return None


def _slice_view(scene: dict[str, Any], view: Any, index: int) -> dict[str, Any]:
    if not isinstance(view, dict):
        raise ValueError(f"View {index}: selection must be an object.")
    kind = view.get("kind")
    offset, limit = _line_window(view, index)
    if kind == "check":
        text, total = _check_text(scene, view, index)
    elif kind == "diff":
        text, total = _diff_text(scene, view, index)
    else:
        raise ValueError(f"View {index}: kind must be 'check' or 'diff'.")
    window, truncated = _window_text(text, offset, limit)
    from evolver.gep.val_seal import redact

    sealed, _report = redact(window, where="episode_inspect")
    return {
        "index": index,
        "kind": kind,
        "name": view.get("name"),
        "path_glob": view.get("path_glob"),
        "offset_lines": offset,
        "limit_lines": limit,
        "total_lines": total,
        "truncated": truncated,
        "text": sealed,
        "source": "engine",
    }


def _line_window(view: dict[str, Any], index: int) -> tuple[int, int]:
    offset = view.get("offset_lines", 0)
    limit = view.get("limit_lines", 80)
    if not _plain_int(offset) or offset < 0:
        raise ValueError(f"View {index}: offset_lines must be an integer >= 0.")
    if not _plain_int(limit) or not 1 <= limit <= MAX_INSPECT_LIMIT_LINES:
        raise ValueError(
            f"View {index}: limit_lines must be an integer from 1 to {MAX_INSPECT_LIMIT_LINES}."
        )
    return offset, limit


def _check_text(scene: dict[str, Any], view: dict[str, Any], index: int) -> tuple[str, int]:
    name = view.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"View {index}: check views need a name.")
    validation = scene.get("validation_result")
    results = validation.get("results") if isinstance(validation, dict) else None
    if not isinstance(results, list):
        raise ValueError(f"View {index}: the scene has no check results.")
    needle = name.strip().lower()
    for entry in results:
        if not isinstance(entry, dict):
            continue
        command = _text(entry.get("command"))
        if needle not in command.lower():
            continue
        stdout = _text(entry.get("stdout"))
        stderr = _text(entry.get("stderr"))
        text = f"$ {command}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return text, len(text.splitlines())
    raise ValueError(f"View {index}: no check named {name!r}.")


def _diff_text(scene: dict[str, Any], view: dict[str, Any], index: int) -> tuple[str, int]:
    from pathlib import PurePosixPath

    pattern = view.get("path_glob")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError(f"View {index}: diff views need a path_glob.")
    event = scene.get("event")
    diff = _text(event.get("diff_snapshot") if isinstance(event, dict) else "")
    chunks = _split_diff(diff)
    matched = [
        text for path, text in chunks if path == "*" or PurePosixPath(path).match(pattern.strip())
    ]
    if not matched:
        raise ValueError(f"View {index}: no diff hunk matches {pattern!r}.")
    text = "\n".join(matched)
    return text, len(text.splitlines())


def _split_diff(diff: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^diff --git a/(.+?) b/(.+)$", diff))
    if not matches:
        return [("*", diff)]
    chunks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(diff)
        chunks.append((match.group(2), diff[match.start() : end]))
    return chunks


def _window_text(text: str, offset: int, limit: int) -> tuple[str, bool]:
    lines = text.splitlines()
    window = "\n".join(lines[offset : offset + limit])
    truncated = offset + limit < len(lines)
    if len(window) > MAX_INSPECT_VIEW_CHARS:
        window = window[:MAX_INSPECT_VIEW_CHARS] + "\n... (inspect window truncated)"
        truncated = True
    return window, truncated


def _plain_int(value: Any) -> TypeGuard[int]:
    """True for an int that is not a bool (bool is a subclass of int)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _clip(value: Any, limit: int) -> str:
    """Clip to *limit* characters, marker included — a bounded view stays bounded."""
    text = _text(value)
    if len(text) <= limit:
        return text
    marker = "... (truncated)"
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)] + marker


__all__ = [
    "ATTRIBUTION_VERDICTS",
    "ENGINE_SIDE_FIELDS",
    "EPISODES_DIRNAME",
    "EPISODE_FILENAME",
    "EPISODE_FORMAT",
    "EPISODE_INDEX_FORMAT",
    "HOST_SIDE_KEYS",
    "INDEX_FILENAME",
    "INSPECT_CALLS_FILENAME",
    "MAX_CHECKS",
    "MAX_CHECK_OUTPUT_CHARS",
    "MAX_DIFF_CHARS",
    "MAX_INSPECT_LIMIT_LINES",
    "MAX_INSPECT_QUESTION_CHARS",
    "MAX_INSPECT_VIEWS",
    "MAX_INSPECT_VIEW_CHARS",
    "MAX_RECORD_CHARS",
    "EpisodeConflictError",
    "attach_behavioral_contrast",
    "attach_component_attribution",
    "attribution_note",
    "behavioral_contrast_note",
    "build_episode",
    "ceiling_tie_note",
    "compute_behavioral_contrast",
    "compute_component_attribution",
    "episode_id",
    "episode_path",
    "episodes_dir",
    "find_episode_id_for_run",
    "index_path",
    "inspect_calls_path",
    "inspect_episode_scene",
    "list_episodes",
    "load_episode",
    "load_index",
    "load_inspect_calls",
    "note_inspect_call",
    "record_episode",
    "record_round",
    "render_episode_block",
    "round_key",
    "validate_episode",
]
