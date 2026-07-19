"""Session-start hook — inject relevant evolution memory into the IDE session.

Equivalent to ``evolver/src/adapters/scripts/evolver-session-start.js`` (309 lines).

Called by the IDE when a new session starts. Reads recent evolution memory
from the workspace-scoped memory graph and emits JSON to stdout with an
``additionalContext`` / ``agent_message`` field the host can splice into the
session's opening context.

Key behaviours ported from the Node.js reference:

- **Host-env project dir**: uses :func:`resolve_project_dir` (reads
  ``CURSOR_PROJECT_DIR`` / ``CLAUDE_PROJECT_DIR``), never ``os.getcwd``
  blindly — Cursor runs hooks with cwd set to the plugin dir.
- **Workspace scoping**: reads only entries whose ``workspace_id`` (or legacy
  ``cwd``) matches the current workspace, so projects sharing a user-level
  fallback graph never cross-pollinate (#105/#555).
- **Non-git notice**: emits a one-line "evolution memory is inactive" notice
  (throttled to once per 30 min per folder) when the workspace is not a git
  repo (#558).
- **Lazy memory read**: parses the graph file from the newest end and stops
  as soon as ``n`` workspace-matching entries are found (#555 round-3).
- **Dedup**: on per-prompt-firing platforms (Kiro), suppresses re-injection
  within a TTL window.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import suppress
from pathlib import Path

NON_GIT_NOTICE = (
    "[Evolver] This folder is not a git repository, so evolution memory is inactive "
    "(outcomes are derived from git diffs). Run `git init` here, or open a git project, "
    "to enable recall and recording."
)
NON_GIT_NOTICE_TTL_S = 30 * 60  # once per 30 min per folder


# ---------------------------------------------------------------------------
# State throttling (dedup + notice)
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    d = Path(os.environ.get("EVOLVER_SESSION_STATE_DIR", Path.home() / ".evolver"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_dedup_state_path() -> Path:
    return _state_dir() / "session-start-state.json"


def _get_notice_state_path() -> Path:
    return _state_dir() / "session-start-notice-state.json"


def _throttled(key: str, ttl_s: float, state_path: Path) -> bool:
    """Return True if *key* fired within *ttl_s* (suppress); else record now.

    Best-effort: a state read/write failure means no throttling (fail open).
    """
    state: dict[str, float] = {}
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
    except (OSError, json.JSONDecodeError):
        state = {}

    now = time.time()
    last = state.get(key)
    if isinstance(last, (int, float)) and now - last < ttl_s:
        return True

    state[key] = now
    try:
        # Prune entries older than 24h.
        cutoff = now - 24 * 60 * 60
        state = {k: v for k, v in state.items() if isinstance(v, (int, float)) and v > cutoff}
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(state_path)
    except OSError:
        pass
    return False


def _should_skip_injection() -> bool:
    """Dedup guard for per-prompt-firing platforms (Kiro)."""
    raw = os.environ.get("EVOLVER_SESSION_START_DEDUP", "")
    if raw.lower() not in ("1", "true"):
        return False
    ttl_s = float(os.environ.get("EVOLVER_SESSION_START_DEDUP_TTL_S", "1800"))
    return _throttled(os.getcwd(), ttl_s, _get_dedup_state_path())


# ---------------------------------------------------------------------------
# Memory reading (workspace-scoped, newest-first)
# ---------------------------------------------------------------------------


def belongs_to_workspace(
    entry: dict[str, object],
    current_id: str | None,
    current_dir: str | None,
) -> bool:
    """Does this memory-graph entry belong to the current workspace?

    Rules (mirror ``belongsToWorkspace`` in the Node reference):
      - entry has ``workspace_id`` + current_id known → must match exactly.
      - entry has ``workspace_id`` but current_id unknown → show it.
      - entry has only ``cwd`` + current_dir known → must match.
      - untagged (legacy/Hub) → never excluded.
    """
    ws_id = entry.get("workspace_id")
    if isinstance(ws_id, str) and ws_id:
        if current_id:
            return ws_id == current_id
        return True
    cwd = entry.get("cwd")
    if isinstance(cwd, str) and cwd:
        if current_dir:
            return cwd == current_dir
        return True
    return True


def _read_recent_workspace_entries(
    file_path: Path,
    current_id: str | None,
    current_dir: str | None,
    n: int,
) -> list[dict[str, object]]:
    """Return up to *n* most-recent workspace entries, oldest-first.

    Parses from the newest end and stops as soon as *n* matches are found
    (#555 round-3 — avoids parsing the entire file on large graphs).
    """
    try:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
    except OSError:
        return []

    lines = text.split("\n")
    out: list[dict[str, object]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if belongs_to_workspace(entry, current_id, current_dir):
            out.append(entry)
            if len(out) >= n:
                break
    out.reverse()  # newest-collected-first → chronological
    return out


def _format_outcome(entry: dict[str, object]) -> str:
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    status = outcome.get("status", "unknown")
    score = outcome.get("score", "?")
    note = outcome.get("note", "")
    signals_val = entry.get("signals")
    signals = ", ".join(signals_val[:3]) if isinstance(signals_val, list) else ""
    ts_val = entry.get("timestamp", "")
    ts = str(ts_val)[:10] if ts_val else ""
    icon = "+" if status == "success" else ("-" if status == "failed" else "?")
    line = f"[{icon}] {ts} score={score} signals=[{signals}] {note}"
    return line[:200]


# ---------------------------------------------------------------------------
# Main hook entry
# ---------------------------------------------------------------------------


def build_session_context(*, cwd: Path | None = None) -> dict[str, str]:
    """Build the session-start JSON output (empty dict if nothing to inject)."""
    if _should_skip_injection():
        return {}

    try:
        from evolver.adapters.scripts.memory_filtering import (
            filter_relevant_outcomes,
        )
        from evolver.adapters.scripts.runtime_paths import (
            find_evolver_root,
            find_memory_graph,
            is_git_workspace,
            resolve_project_dir,
            resolve_workspace_id,
        )
    except ImportError:
        return {}

    current_dir = cwd or resolve_project_dir()
    parts: list[str] = []

    # Non-git notice (throttled).
    if not is_git_workspace(current_dir):
        key = f"nongit:{current_dir}"
        if not _throttled(key, NON_GIT_NOTICE_TTL_S, _get_notice_state_path()):
            parts.append(NON_GIT_NOTICE)

    evolver_root = find_evolver_root()
    graph_path = find_memory_graph(evolver_root)

    if graph_path and graph_path.exists():
        current_id = resolve_workspace_id(evolver_root, current_dir)
        recent = _read_recent_workspace_entries(graph_path, current_id, str(current_dir), 5)
        filtered = filter_relevant_outcomes(recent)
        if filtered:
            success_count = sum(
                1
                for e in filtered
                if isinstance(e.get("outcome"), dict) and e["outcome"].get("status") == "success"
            )
            fail_count = len(filtered) - success_count
            lines = [
                f"[Evolution Memory] Recent {len(filtered)} outcomes "
                f"({success_count} success, {fail_count} failed):",
                *[_format_outcome(e) for e in filtered],
                "",
                "Use successful approaches. Avoid repeating failed patterns.",
            ]
            parts.append("\n".join(lines))

    if not parts:
        return {}

    out = "\n\n".join(parts)
    return {"agent_message": out, "additionalContext": out}


def main() -> None:
    # Read stdin payload (IDE provides session metadata / transcript records).
    try:
        from evolver.evolve.utils import extract_transcript_cwd, resolve_session_scope

        raw = ""
        with suppress(OSError):
            raw = sys.stdin.read()

        cwd: Path | None = None
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            records: list[dict[str, object]] = []
            if isinstance(parsed, list):
                records = parsed
            elif isinstance(parsed, dict):
                records = [parsed]

            extracted = extract_transcript_cwd(records)
            if extracted:
                cwd = extracted

        # Resolve session scope from transcript cwd for scoped evolution state.
        scope = resolve_session_scope(cwd=cwd, agent_name=os.environ.get("AGENT_NAME"))
        if scope and scope != "default":
            os.environ["EVOLVER_SESSION_SCOPE"] = scope
    except ImportError:
        pass

    output = build_session_context(cwd=cwd)
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
