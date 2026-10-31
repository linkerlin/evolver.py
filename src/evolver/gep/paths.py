"""Central path resolution with env overrides and secure workspace-ID management.

Equivalent to evolver/src/gep/paths.js.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WARNED_LEGACY_PATHS: set[str] = set()


def _warn_legacy_once(key: str, message: str) -> None:
    if os.environ.get("EVOLVER_QUIET_LEGACY_WARNING") == "1":
        return
    if key in _WARNED_LEGACY_PATHS:
        return
    _WARNED_LEGACY_PATHS.add(key)
    print(f"[paths] WARNING: {message}", file=sys.stderr)


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


def get_evolver_state_root() -> Path:
    """Return externalized runtime state root (default: ``~/.evolver``).

    Honors ``EVOLVER_STATE_ROOT`` first, then ``get_evolver_settings_dir()``.
    """
    raw = os.environ.get("EVOLVER_STATE_ROOT")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return get_evolver_settings_dir().expanduser().resolve()


def _walk_up_for_git(start: Path) -> Path | None:
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            return path
        if (path / ".evolver" / "no-parent-git").exists():
            return None
    return None


def _read_config_repo_root() -> Path | None:
    for base in (get_evolver_state_root(), get_evolver_settings_dir()):
        cfg_path = base / "config.json"
        if not cfg_path.is_file():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        raw = data.get("repo_root") or data.get("default_repo_root")
        if isinstance(raw, str) and raw.strip():
            cand = Path(raw.strip()).expanduser()
            if cand.is_dir():
                found = _walk_up_for_git(cand.resolve())
                if found is not None:
                    return found
    return None


def discover_git_candidates(cwd: Path | str | None = None, *, max_depth: int = 2) -> list[str]:
    """Scan subdirectories under ``cwd`` (up to ``max_depth``) for ``.git``."""
    base = Path(cwd or os.getcwd()).expanduser().resolve()
    if not base.is_dir():
        return []
    skip_names = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".evolver",
    }
    found: list[str] = []

    def _scan(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir() or entry.name in skip_names or entry.name.startswith("."):
                continue
            if (entry / ".git").exists():
                found.append(str(entry.resolve()))
            elif depth < max_depth:
                _scan(entry, depth + 1)

    _scan(base, 1)
    return found


def get_repo_root(cwd: Path | str | None = None, *, _quiet: bool | None = None) -> Path | None:
    """Walk upward from cwd looking for .git directory.

    Honors EVOLVER_REPO_ROOT, EVOLVER_PROJECT_DIR, host workspace env vars,
    ~/.evolver/config.json, and EVOLVER_NO_PARENT_GIT.
    """
    if _quiet is None:
        _quiet = os.environ.get("EVOLVER_QUIET_PARENT_GIT") == "1"

    env_root = os.environ.get("EVOLVER_REPO_ROOT") or os.environ.get("EVOLVER_PROJECT_DIR")
    if env_root and env_root.strip():
        p = Path(env_root.strip()).expanduser().resolve()
        git_from_env = (
            _walk_up_for_git(p) if os.environ.get("EVOLVER_NO_PARENT_GIT") != "1" else None
        )
        chosen = git_from_env if git_from_env is not None else p
        if not _quiet:
            print(f"[paths] Using EVOLVER_REPO_ROOT: {chosen}", file=sys.stderr)
        return chosen

    if os.environ.get("EVOLVER_NO_PARENT_GIT") == "1":
        return None

    start = Path(cwd or os.getcwd()).resolve()
    direct = _walk_up_for_git(start)
    if direct is not None:
        if not _quiet:
            print(f"[paths] Using host git repository at: {direct}", file=sys.stderr)
        return direct

    # Check host project env vars and ~/.evolver/config.json as fallback
    for env_key in (
        "OPENCLAW_WORKSPACE",
        "WORKSPACE_DIR",
        "CURSOR_PROJECT_DIR",
        "CLAUDE_PROJECT_DIR",
    ):
        raw_ws = os.environ.get(env_key)
        if raw_ws and raw_ws.strip():
            cand = Path(raw_ws.strip()).expanduser()
            if cand.is_dir():
                found = _walk_up_for_git(cand.resolve())
                if found is not None:
                    if not _quiet:
                        print(
                            f"[paths] Using {env_key} git repository at: {found}", file=sys.stderr
                        )
                    return found
    cfg_repo = _read_config_repo_root()
    if cfg_repo is not None:
        if not _quiet:
            print(f"[paths] Using config.json git repository at: {cfg_repo}", file=sys.stderr)
        return cfg_repo

    return None


def get_workspace_root() -> Path:
    """Return workspace root for mutation/state.

    Precedence: EVOLVER_REPO_ROOT / EVOLVER_PROJECT_DIR (product pin) →
    OPENCLAW_WORKSPACE / WORKSPACE_DIR → get_repo_root() → cwd.
    """
    pin = os.environ.get("EVOLVER_REPO_ROOT") or os.environ.get("EVOLVER_PROJECT_DIR")
    if pin and pin.strip():
        return Path(pin.strip()).expanduser().resolve()
    env = os.environ.get("OPENCLAW_WORKSPACE") or os.environ.get("WORKSPACE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    repo = get_repo_root()
    if repo:
        return repo
    return Path.cwd()


def compute_workspace_id(repo_root: Path | str | None = None) -> str:
    """Compute deterministic external workspace-id without writing into the repo.

    Precedence:
    1. ``EVOLVER_WORKSPACE_ID`` or ``WORKSPACE_ID`` env var
    2. ``<target>/.evolver-workspace-id`` file (optional single-line override)
    3. ``sha256(realpath(target))[:16]``
    """
    for env_key in ("EVOLVER_WORKSPACE_ID", "WORKSPACE_ID"):
        raw_env = os.environ.get(env_key)
        if raw_env and raw_env.strip():
            return raw_env.strip()

    if repo_root is not None:
        target = Path(repo_root).expanduser().resolve()
    else:
        explicit_ws = (
            os.environ.get("EVOLVER_REPO_ROOT")
            or os.environ.get("EVOLVER_PROJECT_DIR")
            or os.environ.get("OPENCLAW_WORKSPACE")
            or os.environ.get("WORKSPACE_DIR")
        )
        if explicit_ws and explicit_ws.strip():
            cand = Path(explicit_ws.strip()).expanduser().resolve()
            git_cand = (
                _walk_up_for_git(cand) if os.environ.get("EVOLVER_NO_PARENT_GIT") != "1" else None
            )
            target = git_cand.resolve() if git_cand is not None else cand
        else:
            repo = get_repo_root(_quiet=True)
            target = repo.resolve() if repo is not None else get_workspace_root().resolve()

    override_file = target / ".evolver-workspace-id"
    if override_file.is_file():
        try:
            for line in override_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped
        except OSError:
            pass

    return hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:16]


def get_workspace_state_dir(repo_root: Path | str | None = None) -> Path:
    """Return ``~/.evolver/workspaces/<workspace-id>`` for the target workspace."""
    ws_id = compute_workspace_id(repo_root)
    return get_evolver_state_root() / "workspaces" / ws_id


def ensure_workspace_meta(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Ensure ``meta.json`` exists inside ``~/.evolver/workspaces/<workspace-id>/``."""
    if repo_root is not None:
        target = Path(repo_root).expanduser().resolve()
    else:
        repo = get_repo_root(_quiet=True)
        target = repo.resolve() if repo is not None else get_workspace_root().resolve()

    ws_id = compute_workspace_id(target)
    state_dir = get_evolver_state_root() / "workspaces" / ws_id
    state_dir.mkdir(parents=True, exist_ok=True)
    meta_path = state_dir / "meta.json"
    existing: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}

    now_iso = datetime.now(UTC).isoformat()
    meta: dict[str, Any] = {
        "workspace_id": ws_id,
        "repo_root": str(target),
        "display_name": target.name or str(target),
        "created_at": existing.get("created_at") or now_iso,
        "updated_at": now_iso,
    }
    if existing != meta:
        try:
            tmp = meta_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(meta_path)
        except OSError:
            pass
    return meta


def detect_legacy_in_repo_state(
    repo_root: Path | str | None = None,
    *,
    warn: bool = False,
) -> dict[str, Any]:
    """Check whether legacy in-repo ``memory/evolution`` or ``.evolver/gep`` exist."""
    if repo_root is not None:
        target = Path(repo_root).expanduser().resolve()
    else:
        repo = get_repo_root(_quiet=True)
        target = repo.resolve() if repo is not None else get_workspace_root().resolve()

    state_dir = get_workspace_state_dir(target).resolve()
    legacy_evo = target / "memory" / "evolution"
    legacy_gep = target / ".evolver" / "gep"

    has_evo = (
        legacy_evo.is_dir()
        and legacy_evo.resolve() != (state_dir / "evolution").resolve()
        and any(legacy_evo.iterdir())
    )
    has_gep = (
        legacy_gep.is_dir()
        and legacy_gep.resolve() != (state_dir / "gep").resolve()
        and any(legacy_gep.iterdir())
    )
    has_legacy = bool(has_evo or has_gep)
    info: dict[str, Any] = {
        "has_legacy": has_legacy,
        "legacy_evolution_dir": str(legacy_evo) if has_evo else None,
        "legacy_gep_dir": str(legacy_gep) if has_gep else None,
        "state_root": str(state_dir),
        "migrate_command": "evolver migrate-state",
    }
    if warn and has_legacy:
        _warn_legacy_once(
            str(target),
            f"Legacy in-repo runtime state detected under {target} "
            f"(evolution={info['legacy_evolution_dir']}, gep={info['legacy_gep_dir']}). "
            f"Default state root is now {state_dir}. Run 'evolver migrate-state' to migrate.",
        )
    return info


def resolve_legacy_read_path(primary: Path, legacy_candidates: list[Path]) -> Path:
    """Phase 1 reader: prefer external ``primary``, fall back to legacy with warning."""
    if primary.exists():
        return primary
    for cand in legacy_candidates:
        try:
            if cand.exists() and cand.resolve() != primary.resolve():
                _warn_legacy_once(
                    f"read:{cand}",
                    f"Reading legacy state path {cand} (primary {primary} not found). "
                    "Run 'evolver migrate-state' to migrate state to ~/.evolver/workspaces/.",
                )
                return cand
        except OSError:
            continue
    return primary


def get_logs_dir() -> Path:
    """Return logs directory (externalized under workspace state dir by default)."""
    env = os.environ.get("EVOLVER_LOGS_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_state_dir() / "logs"


def get_evolver_log_path() -> Path:
    return get_logs_dir() / "evolution.log"


def get_memory_dir() -> Path:
    """Return workspace state root (or ``MEMORY_DIR`` override) so ``evolution/`` nests directly."""
    env = os.environ.get("MEMORY_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_state_dir()


def get_evolution_dir() -> Path:
    """Return evolution runtime directory (``~/.evolver/workspaces/<id>/evolution`` by default)."""
    env = os.environ.get("EVOLUTION_DIR")
    if env:
        return Path(env).expanduser()
    scope = os.environ.get("EVOLVER_SESSION_SCOPE")
    base = get_memory_dir() / "evolution"
    if scope:
        return base / scope
    return base


def get_gep_assets_dir() -> Path:
    """Return GEP assets directory (``~/.evolver/workspaces/<id>/gep`` by default)."""
    env = os.environ.get("GEP_ASSETS_DIR")
    if env:
        return Path(env).expanduser()
    return get_workspace_state_dir() / "gep"


def get_mailbox_dir(repo_root: Path | str | None = None) -> Path:
    """Return local proxy-mailbox directory (externalized by default, Phase 1 legacy fallback)."""
    root = (
        Path(repo_root).expanduser().resolve()
        if repo_root
        else (get_repo_root(_quiet=True) or Path.cwd())
    )
    legacy = root / ".evolver" / "proxy-mailbox"
    if legacy.is_dir() or os.environ.get("EVOLUTION_DIR") or os.environ.get("GEP_ASSETS_DIR"):
        return legacy
    return get_workspace_state_dir(root) / "proxy-mailbox"


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
    return get_workspace_state_dir() / "workspace-id"


def get_workspace_id() -> str:
    """Read or generate a stable workspace identifier (externalized under workspace state dir)."""
    primary = get_workspace_id_path()
    legacy = get_workspace_root() / ".evolver" / "workspace-id"
    path = resolve_legacy_read_path(primary, [legacy])
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if len(raw) == 32 and all(c in "0123456789abcdef" for c in raw.lower()):
            return raw.lower()
    new_id = secrets.token_hex(16)
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_text(new_id, encoding="utf-8")
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
