"""Session-end hook — record the evolution outcome at session end.

Equivalent to ``evolver/src/adapters/scripts/evolver-session-end.js`` (321 lines).

Collects git diff stats, extracts signals from the diff, and records the
outcome to the local memory graph (and optionally the Hub). Emits JSON to
stdout with a ``systemMessage`` field (Claude Code Stop-hook notification) —
or an empty ``{}`` on Cursor where ``systemMessage`` is mishandled.

Key behaviours ported from the Node.js reference:

- **Host-env project dir**: uses :func:`resolve_project_dir` for git diff
  collection and workspace tagging (#554).
- **Workspace-id stamping**: every entry gets a ``workspace_id`` (forge-
  resistant) and a legacy ``cwd`` tag, so the session-start reader can scope
  (#105/#555).
- **HEAD~1 vs working-tree diff**: tries ``git diff HEAD~1`` first; falls
  back to the working-tree diff only when HEAD~1 is unavailable (#94 round-6).
- **No-changes breadcrumb**: when there is nothing to record (no diff / not a
  repo), writes a log breadcrumb instead of fabricating an empty outcome
  (#555).
- **Cursor suppression**: omits ``systemMessage`` on Cursor (where it would
  be spliced into the next inference round).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

_MAX_EXEC_BUFFER = 10 * 1024 * 1024  # 10 MB — prevents RangeError on large repos

# Regexes for signal extraction from the diff content.
_SIGNAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("log_error", re.compile(r"error:|exception:|failed", re.IGNORECASE)),
    ("perf_bottleneck", re.compile(r"timeout|slow|latency|bottleneck", re.IGNORECASE)),
    (
        "user_feature_request",
        re.compile(r"add|implement|feature|new function|new module", re.IGNORECASE),
    ),
    (
        "user_improvement_suggestion",
        re.compile(r"improve|enhance|refactor|optimize", re.IGNORECASE),
    ),
    (
        "capability_gap",
        re.compile(r"not supported|unsupported|not implemented", re.IGNORECASE),
    ),
    ("deployment_issue", re.compile(r"deploy|ci|pipeline|build failed", re.IGNORECASE)),
    ("test_failure", re.compile(r"test fail|assertion|expect\(", re.IGNORECASE)),
]


def _run_git(args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run git, returning (ok, stdout_trimmed). Never raises."""
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            return True, res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return False, ""


def get_git_diff_stats() -> dict[str, object]:
    """Collect git diff statistics using the host-provided workspace root."""
    try:
        from evolver.adapters.scripts.runtime_paths import (
            resolve_project_dir,
        )

        cwd = resolve_project_dir()
    except ImportError:
        cwd = Path.cwd()

    stat_ok, stat_head1 = _run_git(["diff", "--stat", "HEAD~1"], cwd)
    stat = stat_head1 if stat_ok else _run_git(["diff", "--stat"], cwd)[1]
    diff_ok, diff_head1 = _run_git(["diff", "--no-color", "HEAD~1"], cwd)
    diff_content = diff_head1 if diff_ok else _run_git(["diff", "--no-color"], cwd)[1]

    files_changed = "0 files changed"
    if stat:
        m = re.search(r"\d+ files? changed", stat)
        if m:
            files_changed = m.group(0)
    insertions_m = re.search(r"(\d+) insertions?", stat)
    insertions = insertions_m.group(1) if insertions_m else "0"
    deletions_m = re.search(r"(\d+) deletions?", stat)
    deletions = deletions_m.group(1) if deletions_m else "0"
    is_repo = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)[1] == "true"

    return {
        "stat": stat,
        "summary": f"{files_changed}, +{insertions}/-{deletions}",
        "diffSnippet": diff_content[:2000],
        "hasChanges": bool(stat),
        "isRepo": is_repo,
    }


def detect_signals(text: str) -> list[str]:
    """Extract evolution signal tags from diff text."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _SIGNAL_PATTERNS:
        if pattern.search(text):
            found.append(name)
    # Deduplicate preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for s in found:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def is_cursor_host() -> bool:
    """Detect whether the hook runs inside Cursor (suppress systemMessage)."""
    verbose = os.environ.get("EVOLVER_HOOK_VERBOSE", "").lower()
    if verbose in ("1", "true"):
        return False
    if os.environ.get("EVOLVER_HOOK_HOST", "").lower() == "cursor":
        return True
    if os.environ.get("TERM_PROGRAM", "").lower() == "cursor":
        return True
    return bool(os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_SESSION_ID"))


def _append_evolution_log(line: str) -> None:
    """Best-effort append to ~/.evolver/logs/evolution.log."""
    try:
        log_dir = Path(os.environ.get("EVOLVER_HOOK_LOG_DIR", Path.home() / ".evolver" / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "evolution.log").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    except OSError:
        pass


def record_to_local(graph_path: Path, outcome: dict[str, object]) -> bool:
    """Append an outcome entry to the local memory graph (workspace-tagged)."""
    try:
        from evolver.adapters.scripts.runtime_paths import (
            resolve_project_dir,
            resolve_workspace_id,
        )

        project_dir = resolve_project_dir()
    except ImportError:
        project_dir = Path.cwd()
        ws_id: str | None = None
    else:
        ws_id = resolve_workspace_id(None, project_dir)

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gene_id": outcome.get("geneId", "ad_hoc"),
        "signals": outcome.get("signals", []),
        "outcome": {
            "status": outcome.get("status", "unknown"),
            "score": outcome.get("score", 0),
            "note": outcome.get("summary", ""),
        },
        # Always stamp resolve_project_dir() — never process.cwd() — so Cursor
        # plugin-dir hooks still match session-start's project-dir reader (#555).
        "cwd": str(project_dir),
        "workspace_id": ws_id,
        "source": "hook:session-end",
    }
    try:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def _resolve_graph_path() -> Path | None:
    """Prefer MEMORY_GRAPH_PATH env, else runtime_paths discovery."""
    env_path = os.environ.get("MEMORY_GRAPH_PATH", "").strip()
    if env_path:
        return Path(env_path)
    try:
        from evolver.adapters.scripts.runtime_paths import (
            find_evolver_root,
            find_memory_graph,
        )

        evolver_root = find_evolver_root()
        return find_memory_graph(evolver_root)
    except ImportError:
        return None


def build_session_end_output() -> dict[str, str]:
    """Process stdin (if any), collect diffs, record outcome, return output."""
    diff_info = get_git_diff_stats()

    if not diff_info["hasChanges"]:
        reason = (
            "no changes detected this session" if diff_info["isRepo"] else "not a git workspace"
        )
        _append_evolution_log(f"[Evolution] Session end: nothing recorded ({reason}).")
        return {}

    signals = detect_signals(str(diff_info["diffSnippet"]))
    if not signals:
        signals = ["stable_success_plateau"]

    has_errors = "log_error" in signals or "test_failure" in signals
    status = "failed" if has_errors else "success"
    score = 0.3 if has_errors else 0.8

    outcome = {
        "geneId": "ad_hoc",
        "signals": signals,
        "status": status,
        "score": score,
        "summary": f"Session end: {diff_info['summary']}. Signals: [{', '.join(signals)}]",
    }

    graph_path = _resolve_graph_path()
    local_ok = record_to_local(graph_path, outcome) if graph_path else False

    target = "local memory" if local_ok else "nowhere (no Hub or local path)"
    msg = f"[Evolution] Session outcome recorded to {target}: {outcome['summary']}"
    _append_evolution_log(msg)

    if is_cursor_host():
        return {}
    return {"systemMessage": msg}


def main() -> None:
    # Drain stdin and extract cwd from session transcript (if provided).
    payload = ""
    with suppress(OSError):
        payload = sys.stdin.read()

    cwd: Path | None = None
    if payload.strip():
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None

        records: list[dict[str, object]] = []
        if isinstance(parsed, list):
            records = parsed
        elif isinstance(parsed, dict):
            records = [parsed]

        try:
            from evolver.evolve.utils import extract_transcript_cwd

            extracted = extract_transcript_cwd(records)
            if extracted:
                cwd = extracted
        except ImportError:
            pass

    try:
        output = build_session_end_output()
    except Exception:
        output = {}


if __name__ == "__main__":
    main()
