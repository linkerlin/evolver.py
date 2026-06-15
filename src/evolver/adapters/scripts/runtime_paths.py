"""Shared path resolution for adapter runtime scripts.

Equivalent to ``evolver/src/adapters/scripts/_runtimePaths.js`` (440 lines).

Two responsibilities, mirroring the Node.js reference:

1. **Locate the evolver package** — supports ``$EVOLVER_ROOT`` override, the
   dev/colocated layout (``__file__`` walk), the installed package (via
   :func:`importlib.util.find_spec`), and a ``~/skills/evolver`` fallback.
2. **Locate the evolution memory graph** — so that hook scripts in
   environments without an evolver-managed project directory still record
   outcomes somewhere instead of reporting "nowhere" (#536).

Security notes (carry over from the Node implementation):
  - ``resolve_project_dir`` reads the *host* env (``CURSOR_PROJECT_DIR`` /
    ``CLAUDE_PROJECT_DIR``), **never** ``process.cwd`` blindly, because
    Cursor runs some hook events with cwd set to the plugin install dir.
  - ``resolve_workspace_id`` uses an FS-only fallback that writes the same
    ``.evolver/workspace-id`` secret file ``paths.get_workspace_id`` uses, so
    plugin-only installs (no importable package) still produce a stable,
    forge-resistant workspace tag.
"""

from __future__ import annotations

import importlib.util
import os
import re
import secrets
import subprocess
from contextlib import suppress
from pathlib import Path
from re import Pattern
from typing import Final

# ---------------------------------------------------------------------------
# Evolver package discovery
# ---------------------------------------------------------------------------


def _is_evolver_package(pkg_dir: Path) -> bool:
    """Return True if *pkg_dir* looks like the evolver package root."""
    # Check for pyproject.toml or __init__.py with the right identity.
    pyproject = pkg_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
            # Cheap heuristic: name field.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("name") and "=" in stripped:
                    val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    if val in ("evolver",):
                        return True
        except OSError:
            pass
    return (pkg_dir / "src" / "evolver" / "__init__.py").exists() or (
        (pkg_dir / "__init__.py").exists() and pkg_dir.name == "evolver"
    )


def find_evolver_root() -> Path | None:
    """Locate the evolver package root.

    Resolution order (mirrors ``findEvolverRoot`` in ``_runtimePaths.js``):

    1. ``EVOLVER_ROOT`` env override (validated as a real package dir).
    2. Dev/repo layout: walk up from this file
       (``src/evolver/adapters/scripts/runtime_paths.py``).
    3. Installed package via :func:`importlib.util.find_spec`.
    4. ``~/skills/evolver`` fallback.
    """
    # 1. Explicit override.
    env_root = os.environ.get("EVOLVER_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser()
        if _is_evolver_package(candidate) or (candidate / "src" / "evolver").exists():
            return candidate

    # 2. Dev/colocated layout — this file is at
    #    src/evolver/adapters/scripts/runtime_paths.py, so the repo root is
    #    5 levels up.
    here = Path(__file__).resolve()
    repo_root = here.parents[4]  # scripts -> adapters -> evolver -> src -> repo
    if (repo_root / "src" / "evolver" / "__init__.py").exists():
        return repo_root

    # 3. Installed package via import system.
    try:
        spec = importlib.util.find_spec("evolver")
        if spec is not None and spec.origin:
            # spec.origin is .../evolver/__init__.py; package root is 2 up.
            pkg_init = Path(spec.origin).resolve()
            # If installed editable, parents[1] is the repo root.
            repo_candidate = pkg_init.parents[1]
            if (repo_candidate / "src" / "evolver" / "__init__.py").exists():
                return repo_candidate
            # site-packages install: the package dir itself.
            return pkg_init.parent
    except (ModuleNotFoundError, ValueError):
        pass

    # 4. ~/skills/evolver fallback.
    home_skills = Path.home() / "skills" / "evolver"
    if _is_evolver_package(home_skills) or (home_skills / "src" / "evolver").exists():
        return home_skills

    return None


# ---------------------------------------------------------------------------
# Project directory resolution (from host env, not process.cwd)
# ---------------------------------------------------------------------------

#: Host env vars that expose the real workspace root. Cursor and Claude Code
#: set these; Codex/opencode/Kiro and direct CLI do not (cwd is already
#: correct there).
_PROJECT_DIR_ENV_KEYS = ("CURSOR_PROJECT_DIR", "CLAUDE_PROJECT_DIR")


def resolve_project_dir() -> Path:
    """Resolve the user's PROJECT directory from the host environment.

    Hook scripts must NOT assume ``os.getcwd()`` is the project root: Cursor
    invokes some hook events with cwd set to the plugin install dir
    (``~/.cursor/plugins/local/<name>``), not the opened workspace. Hosts
    expose the real workspace root via an env var.

    Only honours an env value that points at an existing directory; stale or
    empty values fall through to ``os.getcwd()``.

    Equivalent to ``resolveProjectDir()`` in ``_runtimePaths.js``.
    """
    for key in _PROJECT_DIR_ENV_KEYS:
        val = os.environ.get(key)
        if val and val.strip():
            try:
                p = Path(val).expanduser()
                if p.is_dir():
                    return p
            except OSError:
                continue
    return Path.cwd()


# ---------------------------------------------------------------------------
# Workspace root + workspace-id (FS-only fallback)
# ---------------------------------------------------------------------------


def _fs_workspace_root(project_dir: Path) -> Path:
    """FS-only re-implementation of ``paths.get_workspace_root()``.

    Mirrors ``_fsWorkspaceRoot`` in ``_runtimePaths.js``:
      1. ``OPENCLAW_WORKSPACE`` override.
      2. Git repo root at/above *project_dir* (with ``workspace/`` subdir step).
      3. *project_dir* itself.
    """
    env_ws = os.environ.get("OPENCLAW_WORKSPACE")
    if env_ws:
        return Path(env_ws).expanduser()

    # Walk up looking for .git entry.
    repo_root: Path | None = None
    for path in [project_dir.resolve(), *project_dir.resolve().parents]:
        if (path / ".git").exists():
            repo_root = path
            break
    if repo_root is None:
        return project_dir

    # Mirror getWorkspaceRoot()'s workspace/ subdir step.
    workspace_dir = repo_root / "workspace"
    if workspace_dir.is_dir():
        return workspace_dir
    return repo_root


_WS_ID_RE: Final[Pattern[str]] = re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE)


def _ws_id_valid(raw: str) -> bool:
    """Return True if *raw* looks like a valid hex workspace id (>=32 hex)."""
    return bool(_WS_ID_RE.match(raw))


def _read_ws_id_guarded(id_file: Path) -> str | None:
    """Read workspace-id with symlink guards.

    Rejects a symlinked ``.evolver`` dir, a symlinked/non-regular id file,
    and non-hex content. Returns the id or ``None`` on any error/missing.

    Equivalent to ``_readWsIdGuarded`` (Bugbot PR #557).
    """
    try:
        evolver_dir = id_file.parent
        if evolver_dir.is_symlink():
            return None
        if not id_file.exists():
            return None
        if id_file.is_symlink() or not id_file.is_file():
            return None
        raw = id_file.read_text(encoding="utf-8").strip()
        return raw if raw and _ws_id_valid(raw) else None
    except OSError:
        return None


def _fs_workspace_id(project_dir: Path) -> str | None:
    """FS-only workspace-id: read or atomically create ``.evolver/workspace-id``.

    Returns ``None`` on ANY read/write error so callers degrade gracefully
    (show everything rather than hide all memory).

    Equivalent to ``_fsWorkspaceId`` in ``_runtimePaths.js``.
    """
    try:
        ws_root = _fs_workspace_root(project_dir)
    except Exception:
        return None
    evolver_dir = ws_root / ".evolver"
    id_file = evolver_dir / "workspace-id"

    # Read first, with symlink guards.
    existing = _read_ws_id_guarded(id_file)
    if existing:
        return existing

    # If the file exists but guards rejected it, refuse to overwrite.
    # Also refuse a symlinked .evolver dir (O_NOFOLLOW only guards final path).
    if (id_file.exists() or id_file.is_symlink()) or evolver_dir.is_symlink():
        return None
    try:
        evolver_dir.mkdir(parents=True, exist_ok=True)
        payload = secrets.token_hex(16)
        # Atomic create: O_WRONLY | O_CREAT | O_EXCL.
        fd = os.open(
            str(id_file),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(fd, (payload + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        with suppress(OSError):
            os.chmod(id_file, 0o600)
        return payload
    except OSError:
        # EEXIST race — re-read with guards.
        return _read_ws_id_guarded(id_file)
    except Exception:
        return None


def resolve_workspace_id(
    evolver_root: Path | None = None,
    project_dir: Path | None = None,
) -> str | None:
    """Resolve the current workspace id (forge-resistant tag).

    Resolution order (mirrors ``resolveWorkspaceId`` in ``_runtimePaths.js``):
      1. ``EVOLVER_WORKSPACE_ID`` env override.
      2. ``paths.get_workspace_id()`` loaded from the resolved evolver root.
      3. FS-only fallback for plugin-only installs.

    Returns ``None`` if even the FS write fails — callers must then NOT filter
    (show everything), preserving prior behavior.
    """
    env_id = os.environ.get("EVOLVER_WORKSPACE_ID")
    if env_id:
        return str(env_id)

    root = evolver_root or find_evolver_root()
    if root is not None:
        try:
            from evolver.gep.paths import get_workspace_id  # noqa: PLC0415

            return get_workspace_id()
        except Exception:
            pass  # paths unreachable — fall through to FS-only

    return _fs_workspace_id(project_dir or resolve_project_dir())


# ---------------------------------------------------------------------------
# Memory graph location
# ---------------------------------------------------------------------------


def find_memory_graph(evolver_root: Path | None = None) -> Path:
    """Return a path to the evolution memory graph (always writable).

    Never returns ``None`` — when no evolver root is available, falls back to
    ``~/.evolver/memory/evolution/memory_graph.jsonl`` so npm-global/pip-global
    installs without a project-local evolver still capture outcomes (#536).

    Equivalent to ``findMemoryGraph`` in ``_runtimePaths.js``.
    """
    env_path = os.environ.get("MEMORY_GRAPH_PATH")
    if env_path:
        return Path(env_path).expanduser()

    root = evolver_root if evolver_root is not None else find_evolver_root()
    if root is not None:
        lower = root / "memory" / "evolution" / "memory_graph.jsonl"
        if lower.exists():
            return lower
        upper = root / "MEMORY" / "evolution" / "memory_graph.jsonl"
        if upper.exists():
            return upper
        # Neither exists — prefer lowercase if root is writable.
        try:
            lower.parent.mkdir(parents=True, exist_ok=True)
            return lower
        except OSError:
            pass

    # User-level fallback. Always writable, consistent across platforms.
    user_dir = Path.home() / ".evolver" / "memory" / "evolution"
    with suppress(OSError):
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "memory_graph.jsonl"


# ---------------------------------------------------------------------------
# Git workspace check
# ---------------------------------------------------------------------------


def is_git_workspace(directory: Path | str | None = None) -> bool:
    """Return True if *directory* is inside a git work tree.

    Cheap, no-shell ``git rev-parse``. Returns False on any error (git
    missing, not a repo, timeout) and never raises.

    Equivalent to ``isGitWorkspace`` in ``_runtimePaths.js``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(directory) if directory else None,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


def find_workspace_root(cwd: Path | str | None = None) -> Path:
    """Find the nearest workspace root containing a git repo.

    .. deprecated::
        Retained for callers that only need a git-root walk. New code should
        use :func:`resolve_project_dir` + :func:`_fs_workspace_root`.
    """
    start = Path(cwd) if cwd else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return start


__all__ = [
    "find_evolver_root",
    "find_memory_graph",
    "find_workspace_root",
    "is_git_workspace",
    "resolve_project_dir",
    "resolve_workspace_id",
]
