"""uv / uvx / python launcher resolution for spawning evolver processes.

Supports three ways to re-invoke the CLI:

* ``python -m evolver …`` — classic (always available)
* ``uv run evolver …`` — project-local tool env (preferred when ``uv`` is on
  PATH and a project root with ``pyproject.toml`` / ``uv.lock`` is found)
* ``uvx evolver …`` — tool isolation (when ``uvx`` is on PATH and no project
  root is required, or when explicitly selected)

Environment
-----------
``EVOLVER_LAUNCHER``
    ``auto`` (default) | ``python`` | ``uv`` | ``uvx``

``EVOLVER_LOOP_COMMAND``
    Full argv override (space-separated). Wins over launcher resolution —
    used by ops lifecycle and advanced supervisors.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Final, Literal

LauncherKind = Literal["auto", "python", "uv", "uvx"]

_VALID_LAUNCHERS: Final[frozenset[str]] = frozenset({"auto", "python", "uv", "uvx"})


def which_uv() -> str | None:
    """Return path to ``uv`` executable if found on PATH."""
    return shutil.which("uv")


def which_uvx() -> str | None:
    """Return path to ``uvx`` executable if found on PATH.

    ``uvx`` is typically a sibling of ``uv`` (same install). On some installs
    only ``uv tool run`` is available — we still look for a bare ``uvx``.
    """
    found = shutil.which("uvx")
    if found:
        return found
    # Fallback: `uvx` may be invoked as `uv tool run` when uvx shim is missing.
    uv = which_uv()
    return uv  # callers distinguish via kind


def resolve_launcher_kind() -> LauncherKind:
    """Parse ``EVOLVER_LAUNCHER`` (default ``auto``)."""
    raw = (os.environ.get("EVOLVER_LAUNCHER") or "auto").strip().lower()
    if raw in _VALID_LAUNCHERS:
        return raw  # type: ignore[return-value]
    return "auto"


def find_project_root(start: Path | str | None = None) -> Path | None:
    """Walk upward for ``pyproject.toml`` or ``uv.lock`` (uv project root)."""
    try:
        cur = Path(start or os.getcwd()).resolve()
    except (OSError, RuntimeError):
        return None
    for path in [cur, *cur.parents]:
        if (path / "pyproject.toml").is_file() or (path / "uv.lock").is_file():
            return path
    return None


def _python_module_cmd(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "evolver", *args]


def _uv_run_cmd(args: list[str], *, uv_bin: str, project: Path | None) -> list[str]:
    # `uv run --project <root> evolver …` keeps the tool env stable when cwd drifts.
    cmd = [uv_bin, "run"]
    if project is not None:
        cmd.extend(["--project", str(project)])
    cmd.append("evolver")
    cmd.extend(args)
    return cmd


def _uvx_cmd(args: list[str], *, uvx_bin: str, project: Path | None) -> list[str]:
    # Prefer package from the current project when available:
    #   uvx --from <project> evolver …
    # Otherwise bare: uvx evolver … (PyPI / tool install).
    name = Path(uvx_bin).name.lower()
    if name in ("uv", "uv.exe"):
        # No uvx shim — use `uv tool run` equivalent surface.
        cmd = [uvx_bin, "tool", "run"]
    else:
        cmd = [uvx_bin]
    if project is not None:
        cmd.extend(["--from", str(project)])
    cmd.append("evolver")
    cmd.extend(args)
    return cmd


def build_evolver_command(
    args: list[str] | None = None,
    *,
    launcher: LauncherKind | str | None = None,
    cwd: Path | str | None = None,
) -> list[str]:
    """Build argv to invoke the evolver CLI with *args* (e.g. ``['--loop']``).

    Resolution order for ``launcher=auto``:
    1. ``EVOLVER_LOOP_COMMAND`` full override (if set and *args* is the loop
       default — see :func:`build_loop_command`)
    2. ``uv run evolver`` when ``uv`` is available and a project root exists
    3. ``uvx evolver`` when ``uvx`` (or ``uv``) is available and no project
       (or ``EVOLVER_LAUNCHER=uvx``)
    4. ``python -m evolver``
    """
    tail = list(args or [])
    kind: LauncherKind
    if launcher is None:
        kind = resolve_launcher_kind()
    else:
        k = str(launcher).strip().lower()
        kind = k if k in _VALID_LAUNCHERS else "auto"  # type: ignore[assignment]

    project = find_project_root(cwd)
    uv_bin = which_uv()
    uvx_bin = which_uvx()

    if kind == "python":
        return _python_module_cmd(tail)

    if kind == "uv":
        if not uv_bin:
            return _python_module_cmd(tail)
        return _uv_run_cmd(tail, uv_bin=uv_bin, project=project)

    if kind == "uvx":
        if not uvx_bin and not uv_bin:
            return _python_module_cmd(tail)
        return _uvx_cmd(tail, uvx_bin=uvx_bin or uv_bin or "uvx", project=project)

    # auto
    if uv_bin and project is not None:
        return _uv_run_cmd(tail, uv_bin=uv_bin, project=project)
    if uvx_bin or uv_bin:
        # Prefer uvx only when no project; with project we already took uv run.
        if project is None and (uvx_bin or uv_bin):
            return _uvx_cmd(tail, uvx_bin=uvx_bin or uv_bin or "uvx", project=None)
    return _python_module_cmd(tail)


def build_loop_command(*, cwd: Path | str | None = None) -> list[str]:
    """Argv for the daemon loop (``--loop``).

    Honours ``EVOLVER_LOOP_COMMAND`` as a full override when set.
    """
    env = os.environ.get("EVOLVER_LOOP_COMMAND", "").strip()
    if env:
        # Windows-friendly split is imperfect; supervisors should pass a simple
        # space-separated argv without embedded spaces in paths.
        return env.split()
    return build_evolver_command(["--loop"], cwd=cwd)


def build_module_command(
    module: str,
    args: list[str] | None = None,
    *,
    launcher: LauncherKind | str | None = None,
    cwd: Path | str | None = None,
) -> list[str]:
    """Build argv to run ``python -m <module>`` (or ``uv run python -m …``).

    Used by IDE hook installers for ``evolver.adapters.scripts.*``.
    """
    tail = list(args or [])
    kind = resolve_launcher_kind() if launcher is None else str(launcher).strip().lower()
    if kind not in _VALID_LAUNCHERS:
        kind = "auto"
    project = find_project_root(cwd)
    uv_bin = which_uv()

    if kind == "python" or (kind == "auto" and not uv_bin):
        return [sys.executable, "-m", module, *tail]

    if kind in ("uv", "auto") and uv_bin:
        cmd = [uv_bin, "run"]
        if project is not None:
            cmd.extend(["--project", str(project)])
        cmd.extend(["python", "-m", module, *tail])
        return cmd

    if kind == "uvx":
        # uvx is for console scripts; fall back to uv run python -m for modules.
        if uv_bin:
            cmd = [uv_bin, "run"]
            if project is not None:
                cmd.extend(["--project", str(project)])
            cmd.extend(["python", "-m", module, *tail])
            return cmd
        return [sys.executable, "-m", module, *tail]

    return [sys.executable, "-m", module, *tail]


def is_uv_managed_cmdline(cmdline: str) -> bool:
    """True if *cmdline* looks like ``uv run evolver`` / ``uvx evolver``."""
    low = str(cmdline or "").lower()
    if "evolver" not in low:
        return False
    return "uv run" in low or "uvx " in low or "uv tool run" in low or low.strip().startswith("uv ")


def describe_launcher() -> dict[str, str | bool | None]:
    """Diagnostic snapshot for ``evolver check`` / status output."""
    kind = resolve_launcher_kind()
    project = find_project_root()
    return {
        "launcher": kind,
        "uv": which_uv(),
        "uvx": which_uvx(),
        "project_root": str(project) if project else None,
        "resolved_loop": " ".join(build_loop_command()),
        "python": sys.executable,
    }


def hook_command_string(module: str, *, cwd: Path | str | None = None) -> str:
    """Shell command string for IDE hooks (forward-slash paths on Windows)."""
    argv = build_module_command(module, cwd=cwd)
    # Quote nothing extra for simple tokens; replace backslashes for JSON configs.
    parts = [p.replace("\\", "/") for p in argv]
    return " ".join(parts)


__all__ = [
    "LauncherKind",
    "build_evolver_command",
    "build_loop_command",
    "build_module_command",
    "describe_launcher",
    "find_project_root",
    "hook_command_string",
    "is_uv_managed_cmdline",
    "resolve_launcher_kind",
    "which_uv",
    "which_uvx",
]
