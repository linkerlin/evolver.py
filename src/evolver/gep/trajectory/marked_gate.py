"""Runtime-session marking gate (Slice 3b / v1).

Strict-by-default discovery filter:

1. Keep only transcripts whose session_id is in ``marked-sessions.jsonl``
   (written by the session-start hook).
2. Exclude sessions the proxy gateway already captured (hash join against
   proxy-traces.jsonl via ``session_id_sha256``).

Open the gates with ``include_unmarked`` / ``include_gateway_captured``
(or the matching env vars).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from evolver.proxy.trace.extractor import hash_trace_value

MARKED_SESSIONS_FILE_ENV = "EVOLVER_MARKED_SESSIONS_FILE"
INCLUDE_UNMARKED_ENV = "EVOLVER_TRAJECTORY_INCLUDE_UNMARKED"
INCLUDE_GATEWAY_CAPTURED_ENV = "EVOLVER_TRAJECTORY_INCLUDE_GATEWAY_CAPTURED"
SESSION_ID_HASH_PREFIX = "session_id_sha256"
MARK_GATE_HEAD_SCAN_BYTES = 64 * 1024
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if value is False or value == 0 or value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def resolve_marked_sessions_file(opts: dict[str, Any] | None = None) -> Path:
    opts = opts or {}
    explicit = opts.get("markedSessionsFile") or opts.get("marked_sessions_file")
    if explicit:
        return Path(str(explicit))
    env = os.environ.get(MARKED_SESSIONS_FILE_ENV, "").strip()
    if env:
        return Path(env)
    home = opts.get("homedir") or os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
    evolver_home = os.environ.get("EVOLVER_HOME", "").strip()
    if evolver_home:
        return Path(evolver_home) / "marked-sessions.jsonl"
    if home:
        return Path(home) / ".evomap" / "marked-sessions.jsonl"
    return Path.home() / ".evomap" / "marked-sessions.jsonl"


def resolve_trace_file(opts: dict[str, Any] | None = None) -> Path:
    opts = opts or {}
    env = os.environ.get("EVOMAP_PROXY_TRACE_FILE", "").strip()
    if env:
        return Path(env)
    home = opts.get("homedir") or os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
    if home:
        return Path(home) / ".evomap" / "proxy-traces.jsonl"
    return Path.home() / ".evomap" / "proxy-traces.jsonl"


def load_marked_session_ids(opts: dict[str, Any] | None = None) -> set[str]:
    path = resolve_marked_sessions_file(opts)
    out: set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            row = json.loads(s)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        sid = str(row.get("session_id") or row.get("sessionId") or "").strip()
        if sid:
            out.add(sid)
    return out


def load_gateway_captured_session_hashes(opts: dict[str, Any] | None = None) -> set[str]:
    path = resolve_trace_file(opts)
    out: set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return out
    prefix = f"{SESSION_ID_HASH_PREFIX}:"
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            row = json.loads(s)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        sid = str(row.get("sessionId") or row.get("session_id") or "").strip()
        if not sid:
            continue
        if sid.startswith(prefix):
            out.add(sid)
        else:
            out.add(hash_trace_value(sid, SESSION_ID_HASH_PREFIX))
    return out


def candidate_session_ids_for_file(file_path: Path | str) -> list[str]:  # noqa: PLR0912
    path = Path(file_path)
    ids: set[str] = set()
    base = path.name
    for suffix in (".jsonl", ".json"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base:
        ids.add(base)
    uuid_match = UUID_RE.search(path.name)
    if uuid_match:
        ids.add(uuid_match.group(0))

    try:
        with path.open("rb") as fh:
            head = fh.read(MARK_GATE_HEAD_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return list(ids)

    newline_idx = head.rfind("\n")
    scannable = head[:newline_idx] if newline_idx >= 0 else head
    for line in scannable.splitlines():
        s = line.strip()
        if not s or s[0] not in "{[":
            continue
        try:
            row = json.loads(s)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        for key in ("session_id", "sessionId", "sessionID", "trajectory_id", "trajectoryId"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                ids.add(val.strip())
        payload = row.get("payload")
        if isinstance(payload, dict):
            for key in ("id", "session_id", "sessionId"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    ids.add(val.strip())
    return list(ids)


def mark_gate_enabled(raw_opt: Any, env: str | None) -> bool:
    """Return True when the gate is enforced (default). Truthy opt/env opens it."""
    if raw_opt is not None:
        return not _truthy(raw_opt)
    if env is not None and str(env).strip() != "":
        return not _truthy(env)
    return True


def build_mark_gate_context(opts: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = opts or {}
    enforce_marked = mark_gate_enabled(
        opts.get("includeUnmarked", opts.get("include_unmarked")),
        os.environ.get(INCLUDE_UNMARKED_ENV),
    )
    exclude_gateway = mark_gate_enabled(
        opts.get("includeGatewayCaptured", opts.get("include_gateway_captured")),
        os.environ.get(INCLUDE_GATEWAY_CAPTURED_ENV),
    )
    return {
        "enforceMarked": enforce_marked,
        "excludeGatewayCaptured": exclude_gateway,
        "marked": load_marked_session_ids(opts) if enforce_marked else set(),
        "gatewayHashes": load_gateway_captured_session_hashes(opts) if exclude_gateway else set(),
    }


def passes_mark_gate(
    file_path: Path | str,
    mark_gate: dict[str, Any],
    discovery: dict[str, Any] | None = None,
) -> bool:
    """True if *file_path* survives the mark + gateway gates."""
    enforce = bool(mark_gate.get("enforceMarked"))
    exclude_gw = bool(mark_gate.get("excludeGatewayCaptured"))
    if not enforce and not exclude_gw:
        return True
    ids = candidate_session_ids_for_file(file_path)
    if enforce:
        marked: set[str] = mark_gate.get("marked") or set()
        if not any(i in marked for i in ids):
            if discovery is not None:
                mg = discovery.setdefault("markGate", {})
                mg["excludedByMark"] = int(mg.get("excludedByMark") or 0) + 1
            return False
    if exclude_gw:
        hashes: set[str] = mark_gate.get("gatewayHashes") or set()
        if any(hash_trace_value(i, SESSION_ID_HASH_PREFIX) in hashes for i in ids):
            if discovery is not None:
                mg = discovery.setdefault("markGate", {})
                mg["excludedByGateway"] = int(mg.get("excludedByGateway") or 0) + 1
            return False
    return True


def collect_runtime_session_inputs(opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Walk runtime session dirs and return files that pass the mark gate.

    *opts* keys (Node-compatible camelCase + snake_case):
    ``runtimeSessions``, ``homedir``, ``runtimeSessionDirs``, ``workspaceRoot``,
    ``includeUnmarked``, ``includeGatewayCaptured``, ``markedSessionsFile``.
    """
    opts = dict(opts or {})
    dirs_raw = opts.get("runtimeSessionDirs") or opts.get("runtime_session_dirs") or []
    if isinstance(dirs_raw, (str, Path)):
        dirs_raw = [dirs_raw]
    runtime_dirs = [Path(d) for d in dirs_raw if d]

    discovery: dict[str, Any] = {
        "enabled": True,
        "dirsScanned": len(runtime_dirs),
        "filesMatched": 0,
    }
    mark_gate = build_mark_gate_context(opts)
    discovery["markGate"] = {
        "enforceMarked": mark_gate["enforceMarked"],
        "excludeGatewayCaptured": mark_gate["excludeGatewayCaptured"],
        "markedSessionCount": len(mark_gate["marked"]),
        "gatewayCapturedCount": len(mark_gate["gatewayHashes"]),
        "excludedByMark": 0,
        "excludedByGateway": 0,
    }

    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in runtime_dirs:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if not (name.endswith(".jsonl") or name.endswith(".json") or name == "wire.jsonl"):
                # also accept session-*.json under gemini chats (covered by ends with .json)
                continue
            # Skip obvious non-session names.
            if name in ("logs.json", "package.json", "tsconfig.json"):
                continue
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            if not passes_mark_gate(path, mark_gate, discovery):
                continue
            seen.add(key)
            files.append({"path": str(path)})
            discovery["filesMatched"] = len(files)

    return {"files": files, "discovery": discovery}


__all__ = [
    "INCLUDE_GATEWAY_CAPTURED_ENV",
    "INCLUDE_UNMARKED_ENV",
    "MARKED_SESSIONS_FILE_ENV",
    "SESSION_ID_HASH_PREFIX",
    "build_mark_gate_context",
    "candidate_session_ids_for_file",
    "collect_runtime_session_inputs",
    "load_gateway_captured_session_hashes",
    "load_marked_session_ids",
    "mark_gate_enabled",
    "passes_mark_gate",
    "resolve_marked_sessions_file",
    "resolve_trace_file",
]
