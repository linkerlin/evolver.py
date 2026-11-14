"""One-touch zero-config bootstrap: ``evolver init`` (支柱零, v1.114.0).

Python-native new module (no Node.js equivalent — the Node original had no
one-touch bootstrap; cf. adapters/setup_hooks.py for host config conventions).

Everything a machine can safely self-bootstrap in the background, it does --
the human never types a config line:

1. Git: reuse an existing repo; in a ``--yes``/effectively-empty directory
   safely ``git init`` + write a safe ``.gitignore``.
2. Legacy runtime state (in-repo ``memory/`` / ``.evolver/gep/``) migrates
   non-destructively to ``~/.evolver/workspaces/<id>/``.
3. Detected IDE hosts (Claude Code / Cursor / Codex / OpenCode / ZCode) get
   their MCP stdio config written idempotently, plus session hooks.
4. A background *clean* subprocess (secrets stripped) establishes the
   Project Native Baseline, the Parent Library snapshot and the out-of-tree
   Anchor — first-write only, never reachable from ``solidify``.

Zero human interaction, zero jargon; ``loop_ready=True`` in well under 3s
because the heavy lifting runs in the detached child.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

BOOTSTRAP_MARKER = "bootstrap_baseline.json"
#: Marker format for the async baseline job status file.
BASELINE_FORMAT = "evolver.project_native_baseline.v1"


class MCPConfigUnsafeError(RuntimeError):
    """Existing host config cannot be safely parsed — the write is refused."""


def _atomic_write_text(path: Path, text: str) -> None:
    """tmp + os.replace (CONTRIBUTING atomic-write rule; PID-suffixed tmp)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


_GITIGNORE_LINES = (
    "# evolver runtime state (kept out of the product repo)",
    ".evolver/",
    "memory/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".env",
)


# ---------------------------------------------------------------------------
# Host detection + idempotent MCP config writing
# ---------------------------------------------------------------------------


def _home() -> Path:
    return Path.home()


def _mcp_entry() -> dict[str, Any]:
    """The MCP stdio server entry every host config points at.

    Resolves against evolver's own installation/checkout root rather than the
    target user repository's ``cwd`` so a user repo's ``pyproject.toml`` or an
    offline sandbox never hijacks the MCP server launch command.
    """
    from evolver.uv_runtime import (
        build_evolver_command,
        find_evolver_root,
        resolve_launcher_kind,
    )

    evolver_root = find_evolver_root()
    if evolver_root is not None or resolve_launcher_kind() != "auto":
        argv = build_evolver_command(["mcp"], cwd=evolver_root)
    else:
        argv = build_evolver_command(["mcp"], launcher="python")
    return {"command": argv[0], "args": argv[1:]}


def detect_hosts(project: Path) -> list[str]:
    """IDE hosts present on this machine (project or user level)."""
    pdir = project
    home = _home()
    hosts: list[str] = []
    if (pdir / ".mcp.json").is_file() or (pdir / ".claude").is_dir() or (home / ".claude").is_dir():
        hosts.append("claude-code")
    if (pdir / ".cursor").is_dir() or (home / ".cursor").is_dir():
        hosts.append("cursor")
    if (
        (pdir / "opencode.json").is_file()
        or (pdir / ".opencode").is_dir()
        or (home / ".opencode").is_dir()
        or (home / ".config" / "opencode").is_dir()
    ):
        hosts.append("opencode")
    if (home / ".codex").is_dir():
        hosts.append("codex")
    if (home / ".zcode").is_dir():
        hosts.append("zcode")
    return hosts


def _merge_json_mcp(path: Path, key: str, entry_name: str) -> str:
    """Merge the evolver MCP entry into a JSON config; returns written/unchanged.

    Round-121 review: an unparseable existing config (JSONC comments, trailing
    commas, syntax errors) ABORTS this host's write — the machine must never
    silently replace a human's host config. The raw text is preserved."""
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MCPConfigUnsafeError(f"{path}: unparseable, not touching it ({exc})") from exc
        if not isinstance(loaded, dict):
            raise MCPConfigUnsafeError(f"{path}: top level is not an object, not touching it")
        data = loaded
    container = data.get(key)
    if not isinstance(container, dict):
        container = {}
        data[key] = container
    entry = container.get(entry_name)
    wanted = _mcp_entry()
    if entry == wanted:
        return "unchanged"
    if path.is_symlink():
        raise MCPConfigUnsafeError(f"{path}: symlinked config, not touching it")
    container[entry_name] = wanted
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return "written"


def _merge_opencode_mcp(path: Path, entry_name: str) -> str:
    """OpenCode's ``opencode.json`` MCP schema: ``{"type":"local", "command":[...]}``.

    Round-121 review: the previous writer emitted the Claude/Cursor object
    form, which OpenCode's own validation rejects. Same refuse-on-unparseable
    and atomic-write rules as :func:`_merge_json_mcp`."""
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MCPConfigUnsafeError(f"{path}: unparseable, not touching it ({exc})") from exc
        if not isinstance(loaded, dict):
            raise MCPConfigUnsafeError(f"{path}: top level is not an object, not touching it")
        data = loaded
    wanted_argv = _mcp_entry()
    wanted = {
        "type": "local",
        "command": [wanted_argv["command"], *wanted_argv["args"]],
    }
    container = data.get("mcp")
    if not isinstance(container, dict):
        container = {}
        data["mcp"] = container
    if container.get(entry_name) == wanted:
        return "unchanged"
    if path.is_symlink():
        raise MCPConfigUnsafeError(f"{path}: symlinked config, not touching it")
    container[entry_name] = wanted
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return "written"


def _append_toml_mcp(path: Path) -> str:
    """Append the ``[mcp_servers.evolver]`` section to Codex's config.toml.

    Parses with ``tomllib`` (a broken file is refused, not clobbered) and
    refuses symlinked targets (hook_adapter convention)."""
    wanted = _mcp_entry()
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if text:
        try:
            import tomllib

            parsed = tomllib.loads(text)
        except (OSError, ValueError) as exc:
            raise MCPConfigUnsafeError(
                f"{path}: unparseable TOML, not touching it ({exc})"
            ) from exc
        if "evolver" in (parsed.get("mcp_servers") or {}):
            return "unchanged"
    if path.is_symlink():
        raise MCPConfigUnsafeError(f"{path}: symlinked config, not touching it")
    block = (
        "\n[mcp_servers.evolver]\n"
        f"command = {json.dumps(wanted['command'])}\n"
        f"args = {json.dumps(wanted['args'])}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, text + block)
    return "written"


def write_mcp_configs(project: Path, hosts: list[str] | None = None) -> list[dict[str, Any]]:
    """Idempotently write each detected host's MCP stdio config."""
    pdir = project
    home = _home()
    targets: list[tuple[str, Path, str, str]] = []
    if hosts is None:
        hosts = detect_hosts(pdir)
    for host in hosts:
        if host == "claude-code":
            targets.append(("claude-code", pdir / ".mcp.json", "mcpServers", "evolver"))
        elif host == "cursor":
            targets.append(("cursor", pdir / ".cursor" / "mcp.json", "mcpServers", "evolver"))
        elif host == "opencode":
            targets.append(("opencode", pdir / "opencode.json", "opencode", "evolver"))
        elif host == "codex":
            targets.append(("codex", home / ".codex" / "config.toml", "", ""))
        elif host == "zcode":
            zcode_cfg = home / ".zcode" / "cli" / "config.json"
            targets.append(("zcode", zcode_cfg, "mcpServers", "evolver"))
    results: list[dict[str, Any]] = []
    for host, path, key, name in targets:
        try:
            if host == "opencode":
                status = _merge_opencode_mcp(path, name)
            else:
                status = _merge_json_mcp(path, key, name) if key else _append_toml_mcp(path)
            results.append({"host": host, "path": str(path), "status": status, "ok": True})
        except (OSError, MCPConfigUnsafeError) as exc:
            results.append(
                {"host": host, "path": str(path), "status": "error", "ok": False, "error": str(exc)}
            )
    return results


# ---------------------------------------------------------------------------
# Git + legacy state
# ---------------------------------------------------------------------------


def _effectively_empty(pdir: Path) -> bool:
    """Nothing but dotfiles/dirs — safe to ``git init`` without asking."""
    return all(entry.name.startswith(".") for entry in pdir.iterdir())


def _ensure_git(pdir: Path, *, yes: bool) -> dict[str, Any]:
    from evolver.gep.git_ops import is_git_repo
    from evolver.gep.paths import get_repo_root

    root = get_repo_root(cwd=pdir)
    if root is not None and is_git_repo(root):
        return {"ok": True, "action": "existing", "repo_root": str(root)}
    if not (yes or _effectively_empty(pdir)):
        return {
            "ok": False,
            "action": "skipped",
            "repo_root": None,
            "error": "not_a_git_repo",
            "hint": "re-run with --yes to initialise a git repository here",
        }
    try:
        subprocess.run(
            ["git", "init"], cwd=pdir, check=True, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "action": "init_failed", "repo_root": None, "error": str(exc)}
    gitignore = pdir / ".gitignore"
    if not gitignore.exists():
        _atomic_write_text(gitignore, "\n".join(_GITIGNORE_LINES) + "\n")
    return {"ok": True, "action": "initialized", "repo_root": str(pdir)}


def _migrate_legacy(pdir: Path) -> dict[str, Any] | None:
    """Move in-repo legacy runtime state to the external workspace (copy)."""
    if not ((pdir / "memory").is_dir() or (pdir / ".evolver").is_dir()):
        return None
    try:
        from evolver.ops.migrate_state import migrate_workspace_state

        report = migrate_workspace_state(pdir)
        return {"ok": bool(report.get("ok", True)), "report": report}
    except Exception as exc:  # never block init on migration trouble
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# The main flow
# ---------------------------------------------------------------------------


def _child_env(pdir: Path) -> dict[str, str]:
    """Clean child environment: secrets stripped, project pinned."""
    from evolver.gep.validation_env import scrub_eval_subprocess_env, validation_env

    env = scrub_eval_subprocess_env(validation_env())
    env["EVOLVER_REPO_ROOT"] = str(pdir)
    return env


def _spawn_baseline_child(pdir: Path) -> dict[str, Any]:
    """Dispatch the detached clean-subprocess baseline bootstrap.

    Writes ``BOOTSTRAP_MARKER`` strictly *before* ``Popen`` so a fast child can
    never have its ``status="done"`` marker overwritten back to ``dispatched``.
    """
    from evolver.uv_runtime import (
        build_evolver_command,
        find_evolver_root,
        resolve_launcher_kind,
    )

    marker_dir = _state_dir(pdir)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / BOOTSTRAP_MARKER
    _atomic_write_text(
        marker_path,
        json.dumps({"status": "dispatched", "started_at": _now()}, ensure_ascii=False) + "\n",
    )
    kwargs: dict[str, Any] = {
        "cwd": str(pdir),
        "env": _child_env(pdir),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":  # pragma: no cover - platform branch
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
    else:
        kwargs["start_new_session"] = True
    evolver_root = find_evolver_root()
    child_launcher = None if resolve_launcher_kind() != "auto" else "python"
    cmd = build_evolver_command(
        ["_bootstrap-baseline", "--project", str(pdir)],
        launcher=child_launcher,
        cwd=evolver_root,
    )
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        _atomic_write_text(
            marker_path,
            json.dumps({"status": "error", "ok": False, "error": str(exc)}, ensure_ascii=False)
            + "\n",
        )
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "pid": proc.pid}


def _state_dir(pdir: Path) -> Path:
    from evolver.gep.paths import get_workspace_state_dir

    return get_workspace_state_dir(pdir)


def load_native_baseline(project: str | Path | None = None) -> dict[str, Any] | None:
    """Read ``project_native_baseline.json`` for *project* if established."""
    from evolver.gep.paths import get_repo_root

    raw = Path(project).expanduser().resolve() if project else None
    repo = raw or get_repo_root(_quiet=True) or Path.cwd().resolve()
    target = _state_dir(repo) / "project_native_baseline.json"
    if not target.is_file():
        return None
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def bootstrap_baseline_now(project: str | Path | None = None) -> dict[str, Any]:
    """The child's work: Project Native Baseline + Parent Library + Anchor.

    First-write only (``O_CREAT | O_EXCL``): existing artifacts are
    reported as ``already_*`` and never overwritten. Runs in a secrets-stripped
    clean subprocess; every step degrades to an honest ``ok=False`` row.
    """
    from evolver.gep.paths import get_repo_root

    raw = Path(project).expanduser().resolve() if project else Path.cwd().resolve()
    pdir = get_repo_root(cwd=raw, _quiet=True) or raw
    steps: list[dict[str, Any]] = []
    prev_repo_env = os.environ.get("EVOLVER_REPO_ROOT")
    os.environ["EVOLVER_REPO_ROOT"] = str(pdir)
    try:
        # 1. Freeze pack (deterministic builtin tasks) — the fitness measuring stick.
        try:
            from evolver.bench.frozen_gate import freeze_charter_pack

            steps.append({"step": "freeze_pack", **freeze_charter_pack(force=False)})
        except Exception as exc:
            steps.append({"step": "freeze_pack", "ok": False, "error": str(exc)})

        # 2. Out-of-tree anchor contracts (refuses to overwrite an installed epoch).
        try:
            from evolver.gep.anchor import install_anchor_suite

            steps.append({"step": "anchor", **install_anchor_suite()})
        except Exception as exc:
            steps.append({"step": "anchor", "ok": False, "error": str(exc)})

        # 3. Parent library snapshot — O_CREAT | O_EXCL first write from bundled seed.
        try:
            from evolver.gep.asset_store import load_genes
            from evolver.gep.library import establish_parent_library, parent_path

            if parent_path().exists():
                steps.append(
                    {"step": "parent_library", "ok": True, "reason": "already_established"}
                )
            else:
                payload = {
                    "kind": "operator_seed",
                    "established_by": "evolver init",
                    "genes": load_genes(),
                }
                steps.append(
                    {
                        "step": "parent_library",
                        **establish_parent_library(payload),
                    }
                )
        except Exception as exc:
            steps.append({"step": "parent_library", "ok": False, "error": str(exc)})

        # 4. Project Native Baseline: the project's own health, measured, no val.
        try:
            steps.append({"step": "native_baseline", **_native_baseline(pdir)})
        except Exception as exc:
            steps.append({"step": "native_baseline", "ok": False, "error": str(exc)})
    finally:
        if prev_repo_env is None:
            os.environ.pop("EVOLVER_REPO_ROOT", None)
        else:
            os.environ["EVOLVER_REPO_ROOT"] = prev_repo_env

    # 5. Mark the job done (status reads this).
    def _step_ok(step: dict[str, Any]) -> bool:
        return bool(step.get("ok", not step.get("error")))

    try:
        marker_dir = _state_dir(pdir)
        marker_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            marker_dir / BOOTSTRAP_MARKER,
            json.dumps(
                {
                    "status": "done",
                    "ok": all(_step_ok(s) for s in steps),
                    "finished_at": _now(),
                    "steps": steps,
                },
                ensure_ascii=False,
            )
            + "\n",
        )
    except OSError:
        pass
    return {"ok": all(_step_ok(s) for s in steps), "steps": steps}


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _native_baseline(pdir: Path) -> dict[str, Any]:
    """Measure the project's own health: pytest collect + AST parse + git HEAD.

    Strictly first-write via ``open("x")`` (``O_CREAT | O_EXCL``).
    """
    import ast
    import re
    import time as _time

    target = _state_dir(pdir) / "project_native_baseline.json"
    if target.exists():
        return {"ok": True, "reason": "already_written", "path": str(target)}

    collect: dict[str, Any] = {"ok": False}
    t0_collect = _time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=pdir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        collect_ms = round((_time.monotonic() - t0_collect) * 1000.0)
        count = 0
        summary_match = re.search(r"\b(\d+)\s+(?:tests?\s+)?collected\b", proc.stdout)
        if summary_match:
            count = int(summary_match.group(1))
        else:
            count = sum(
                1 for ln in proc.stdout.splitlines() if "::" in ln and not ln.startswith("=")
            )
        # rc 5 = "no tests collected" — a legitimate empty project, not a failure.
        collect = {
            "ok": proc.returncode in (0, 5),
            "tests_collected": count,
            "collect_duration_ms": collect_ms,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        collect = {"ok": False, "error": str(exc)}
    py_files = 0
    syntax_errors = 0
    for root_str, dirs, files in os.walk(pdir):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "venv", "__pycache__", ".tox")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            py_files += 1
            try:
                ast.parse((Path(root_str) / fname).read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                syntax_errors += 1
            except OSError:
                continue
    from evolver.gep.git_ops import git_head

    head = git_head(pdir)
    body = {
        "format": BASELINE_FORMAT,
        "repo_root": str(pdir),
        "head": head,
        "written_at": _now(),
        "pytest_collect": collect,
        "ast_health": {"py_files": py_files, "syntax_errors": syntax_errors},
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        from evolver.gep.import_graph import build_or_load_import_graph

        build_or_load_import_graph(pdir)
    try:
        with target.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        return {"ok": True, "reason": "already_written", "path": str(target)}
    return {"ok": True, "reason": "written", "path": str(target), "baseline": body}


def _is_git_tracked(pdir: Path, rel_path: str) -> bool:
    """True when *rel_path* is already tracked in *pdir*'s git index."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel_path.rstrip("/")],
            cwd=pdir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _register_git_local_excludes(pdir: Path, rel_entries: Sequence[str]) -> list[str]:
    """Idempotently record newly created local host configs in ``.git/info/exclude``.

    Keeps ``git status`` 100% clean right after ``evolver init`` without
    mutating the project's tracked ``.gitignore`` or hiding already-tracked files.
    """
    if not rel_entries:
        return []
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=pdir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        raw_excl = Path(proc.stdout.strip())
        exclude_path = raw_excl if raw_excl.is_absolute() else (pdir / raw_excl)
    except (OSError, subprocess.SubprocessError):
        return []

    existing_text = ""
    if exclude_path.is_file():
        try:
            existing_text = exclude_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    existing_lines = {line.strip() for line in existing_text.splitlines() if line.strip()}

    added: list[str] = []
    for entry in rel_entries:
        clean = entry.strip()
        if not clean or clean in existing_lines or f"/{clean}" in existing_lines:
            continue
        if _is_git_tracked(pdir, clean):
            continue
        added.append(f"/{clean}")
        existing_lines.add(f"/{clean}")

    if not added:
        return []

    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        header = "# --- evolver-init local host configs ---"
        block_lines: list[str] = []
        if header not in existing_text:
            block_lines.append(header)
        block_lines.extend(added)
        sep = "\n" if existing_text and not existing_text.endswith("\n") else ""
        _atomic_write_text(exclude_path, existing_text + sep + "\n".join(block_lines) + "\n")
    except OSError:
        return []
    return added


def render_init_human(report: dict[str, Any]) -> str:
    """Plain-language terminal output for ``evolver init`` (zero internal jargon)."""
    git = report.get("git") or {}
    if not report.get("ok"):
        err = git.get("error") or report.get("error") or "unknown"
        if err == "not_a_git_repo":
            return "\n".join(
                [
                    "Evolver 开箱提示：当前目录尚非 Git 仓库（为保护已有文件未自动初始化）",
                    f"  目录   : {report.get('project')}",
                    "  解决方式:",
                    "    1. 若要在此目录安全初始化 Git 仓库并接入：运行 `evolver init --yes`",
                    "    2. 若代码仓库在其他目录：运行 `evolver init --project <仓库路径>`",
                ]
            )
        return f"Evolver 开箱未完成：{git.get('hint') or err}"

    hosts = report.get("hosts") or []
    excluded = report.get("git_excluded") or []
    host_text = ", ".join(hosts) if hosts else "未检测到本地 IDE 目录（连上 MCP 时将自动惰性自举）"
    if hosts and excluded:
        host_text += "（本地配置已静默记入 .git/info/exclude，不污染 git status）"
    lines = [
        "Evolver 一键开箱就绪",
        f"  项目路径     : {report.get('project')}",
        f"  外置工作区   : {report.get('workspace')}",
        f"  IDE 自动接入 : {host_text}",
    ]
    if git.get("action") == "initialized":
        lines.append("  Git 仓库     : 已安全初始化并生成默认 .gitignore")
    if report.get("migration"):
        lines.append("  历史状态迁移 : 已将仓库内遗留运行态迁至外置工作区")
    lines.extend(
        [
            "  基线自举     : 后台干净子进程正在建立项目原生基线与安全契约（零人工干预）",
            "",
            "下一步:",
            "  • 直接打开编辑器对话即可自动驾驶进化",
            "  • 查看健康与收益面板：`evolver status`  |  启动后台守护巡航：`evolver up`",
        ]
    )
    return "\n".join(lines)


def bootstrap(
    *,
    project: str | Path | None = None,
    yes: bool = False,
    spawn: bool = True,
    configure_hosts: bool = True,
    hosts_filter: Sequence[str] | None = None,
) -> dict[str, Any]:
    """``evolver init`` — everything above, plus the human-readable summary."""
    pdir = Path(project).expanduser().resolve() if project else Path.cwd().resolve()
    if not pdir.is_dir():
        return {"ok": False, "error": "not_a_directory", "project": str(pdir)}

    git = _ensure_git(pdir, yes=yes)
    if git.get("repo_root"):
        pdir = Path(str(git["repo_root"])).resolve()
    migration = _migrate_legacy(pdir)

    # Snapshot which project-local host artifacts did NOT exist prior to init,
    # so anything newly materialized on disk can be added to .git/info/exclude.
    candidate_local_paths: tuple[tuple[str, Path], ...] = (
        (".mcp.json", pdir / ".mcp.json"),
        ("opencode.json", pdir / "opencode.json"),
        (".claude/", pdir / ".claude"),
        (".cursor/", pdir / ".cursor"),
        (".codex/", pdir / ".codex"),
        (".opencode/", pdir / ".opencode"),
    )
    absent_before = [rel for rel, target in candidate_local_paths if not target.exists()]

    if not configure_hosts:
        hosts: list[str] = []
    elif hosts_filter:
        allowed = {"claude-code", "cursor", "opencode", "codex", "zcode"}
        hosts = [h.strip() for raw in hosts_filter for h in raw.split(",") if h.strip() in allowed]
    else:
        hosts = detect_hosts(pdir)

    mcp = write_mcp_configs(pdir, hosts) if configure_hosts and hosts else []

    hooks: list[dict[str, Any]] = []
    hook_platforms = [h for h in hosts if h in ("claude-code", "cursor", "codex", "opencode")]
    if configure_hosts and hook_platforms:
        try:
            import contextlib
            import io

            from evolver.adapters.setup_hooks import install_hooks

            for platform in hook_platforms:
                # install_hooks prints progress banners; silence them so
                # `evolver init --json` stays machine-pure (round-121 review).
                # inject_docs=False ensures zero uninvited edits to tracked
                # AGENTS.md / CLAUDE.md in the user's repository.
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    res = install_hooks(
                        platform=platform,
                        project_dir=pdir,
                        inject_docs=False,
                    )
                hooks.append({"platform": platform, **res})
        except Exception as exc:  # hooks must never block the bootstrap
            hooks.append({"platform": "auto", "ok": False, "error": str(exc)})

    created_local = [
        rel for rel, target in candidate_local_paths if rel in absent_before and target.exists()
    ]
    git_excluded = _register_git_local_excludes(pdir, created_local) if git.get("ok") else []

    baseline_job = (
        _spawn_baseline_child(pdir) if spawn else {"ok": True, "pid": None, "inline": True}
    )

    ok = git.get("ok") is True
    return {
        "ok": ok,
        "loop_ready": ok,
        "project": str(pdir),
        "workspace": str(_state_dir(pdir)),
        "git": git,
        "git_excluded": git_excluded,
        "migration": migration,
        "hosts": hosts,
        "mcp_configs": mcp,
        "hooks": hooks,
        "baseline_job": baseline_job,
        "summary": [
            f"Project ready: {pdir}",
            f"Hosts configured: {', '.join(hosts) if hosts else 'none detected'}",
            "Baseline bootstrapping in the background — you can start working now.",
        ],
    }


__all__ = [
    "BASELINE_FORMAT",
    "BOOTSTRAP_MARKER",
    "bootstrap",
    "bootstrap_baseline_now",
    "detect_hosts",
    "load_native_baseline",
    "render_init_human",
    "write_mcp_configs",
]
