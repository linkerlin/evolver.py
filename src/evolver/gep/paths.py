"""Central path resolution with env overrides and secure workspace-ID management.

Equivalent to evolver/src/gep/paths.js.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def get_evolver_home() -> Path:
    """Return per-user evolver state dir (``~/.evomap``).

    Matches Node ``getEvomapDir()``: when ``EVOLVER_HOME`` is set it is used
    as the state directory itself (not as a parent that receives an extra
    ``.evomap`` segment). Default remains ``Path.home() / ".evomap"``.
    """
    raw = os.environ.get("EVOLVER_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".evomap"


def get_evolver_settings_dir() -> Path:
    """Return settings dir. Default: ~/.evolver."""
    raw = os.environ.get("EVOLVER_SETTINGS_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".evolver"


def get_repo_root(cwd: Path | str | None = None, *, _quiet: bool | None = None) -> Path | None:
    """Walk upward from cwd looking for .git directory.

    Honors EVOLVER_REPO_ROOT, EVOLVER_USE_PARENT_GIT, EVOLVER_NO_PARENT_GIT.
    """
    if _quiet is None:
        _quiet = os.environ.get("EVOLVER_QUIET_PARENT_GIT") == "1"

    env_root = os.environ.get("EVOLVER_REPO_ROOT")
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if not _quiet:
            print(f"[paths] Using EVOLVER_REPO_ROOT: {p}")
        return p

    if os.environ.get("EVOLVER_NO_PARENT_GIT") == "1":
        return None

    start = Path(cwd or os.getcwd()).resolve()
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            if not _quiet:
                print(f"[paths] Using host git repository at: {path}")
            return path
        if (path / ".evolver" / "no-parent-git").exists():
            return None

    if os.environ.get("EVOLVER_USE_PARENT_GIT") == "1":
        return None

    return None


def get_workspace_root() -> Path:
    """Return workspace root. Precedence: OPENCLAW_WORKSPACE -> repo root -> cwd."""
    env = os.environ.get("OPENCLAW_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    repo = get_repo_root()
    if repo:
        return repo
    return Path.cwd()


def get_logs_dir() -> Path:
    """Return logs directory."""
    env = os.environ.get("EVOLVER_LOGS_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_root() / "logs"


def get_evolver_log_path() -> Path:
    return get_logs_dir() / "evolution.log"


def get_memory_dir() -> Path:
    env = os.environ.get("MEMORY_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_root() / "memory"


def get_evolution_dir() -> Path:
    env = os.environ.get("EVOLUTION_DIR")
    if env:
        return Path(env).expanduser()
    scope = os.environ.get("EVOLVER_SESSION_SCOPE")
    base = get_memory_dir() / "evolution"
    if scope:
        return base / scope
    return base


def get_gep_assets_dir() -> Path:
    env = os.environ.get("GEP_ASSETS_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_root() / ".evolver" / "gep"


def get_bundled_gep_assets_dir() -> Path:
    """Return bundled assets dir within the installed package."""
    import evolver

    pkg = Path(evolver.__file__).resolve().parent
    return pkg / "assets" / "gep"


def get_skills_dir() -> Path:
    env = os.environ.get("SKILLS_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_root() / "skills"


def get_session_scope() -> str | None:
    return os.environ.get("EVOLVER_SESSION_SCOPE") or None


def get_agent_sessions_dir() -> Path:
    env = os.environ.get("AGENT_SESSIONS_DIR")
    if env:
        return Path(env).expanduser()
    name = os.environ.get("AGENT_NAME") or "main"
    home = Path.home()
    return home / ".openclaw" / "agents" / name / "sessions"


def get_workspace_id_path() -> Path:
    return get_workspace_root() / ".evolver" / "workspace-id"


def get_workspace_id() -> str:
    """Read or generate a stable workspace identifier."""
    path = get_workspace_id_path()
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if len(raw) == 32 and all(c in "0123456789abcdef" for c in raw.lower()):
            return raw.lower()
    new_id = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_id, encoding="utf-8")
    return new_id


def get_narrative_path() -> Path:
    return get_evolution_dir() / "evolution_narrative.md"


def get_reflection_log_path() -> Path:
    return get_evolution_dir() / "reflection_log.jsonl"


def get_memory_graph_path() -> Path:
    return get_evolution_dir() / "memory_graph.jsonl"


def get_evolution_state_path() -> Path:
    return get_evolution_dir() / "evolution_state.json"


def get_solidify_state_path() -> Path:
    return get_evolution_dir() / "evolution_solidify_state.json"


def get_cycle_progress_path() -> Path:
    return get_evolution_dir() / "cycle_progress.json"


def get_evomap_dir() -> Path:
    return get_evolver_home()


def get_evomap_path(name: str) -> Path:
    return get_evomap_dir() / name


def read_session_cwd_from_head() -> Path | None:
    """Best-effort read cwd from a persisted session head file if present."""
    head = get_evolution_dir() / "session_cwd.head"
    if head.exists():
        raw = head.read_text(encoding="utf-8").strip()
        if raw:
            return Path(raw)
    return None
