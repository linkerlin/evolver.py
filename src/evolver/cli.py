"""Main CLI entry point, equivalent to evolver/index.js."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Sequence


def _load_dotenv() -> None:
    """Load .env BEFORE any internal import so A2A_NODE_SECRET is fresh.

    Matches Node version load order (#460 / #526):
      1. .env at cwd
      2. EVOLVER_REPO_ROOT from process.env (dotenv just populated it)
      3. .env at discovered repo root (dotenv does not overwrite already-set keys)
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    cwd = Path.cwd()
    load_dotenv(dotenv_path=cwd / ".env", override=False)

    prev_quiet = os.environ.get("EVOLVER_QUIET_PARENT_GIT")
    os.environ["EVOLVER_QUIET_PARENT_GIT"] = "1"

    # Lazy import to avoid pulling in heavy modules before env is ready.
    from evolver.gep.paths import get_repo_root

    root = get_repo_root()
    if root and Path(root) != cwd:
        load_dotenv(dotenv_path=Path(root) / ".env", override=False)

    if prev_quiet is None:
        os.environ.pop("EVOLVER_QUIET_PARENT_GIT", None)
    else:
        os.environ["EVOLVER_QUIET_PARENT_GIT"] = prev_quiet


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evolver",
        description="GEP-powered self-evolution engine for AI agents.",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--loop", action="store_true", help="Run as a background daemon")
    parser.add_argument("--mad-dog", action="store_true", help="Alias for --loop")
    parser.add_argument("--review", action="store_true", help="Pause for human review")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Run one evolution cycle (default)")
    sub.add_parser("solidify", help="Apply pending mutation")
    sub.add_parser("review", help="Review pending solidify")
    exec_p = sub.add_parser("exec", help="Execute bridge (opt-in)")
    exec_p.add_argument("--cmd", default=None, help="Command to execute")
    exec_p.add_argument("--timeout", type=int, default=180, help="Timeout in seconds")
    distill_p = sub.add_parser("distill", help="Distill an LLM response")
    distill_p.add_argument("--response-file", default="-", help="Path to response file (use - for stdin)")
    distill_p.add_argument("--dry-run", action="store_true", help="Show what would be installed")
    fetch_p = sub.add_parser("fetch", help="Fetch a skill from the Hub")
    fetch_p.add_argument("query", nargs="?", default="", help="Search query or asset id")
    fetch_p.add_argument("--limit", type=int, default=5, help="Max results to fetch")
    fetch_p.add_argument("--dry-run", action="store_true", help="Show what would be installed")
    sync_p = sub.add_parser("sync", help="Sync assets with the Hub")
    sync_p.add_argument("--dry-run", action="store_true", help="Show what would be synced")
    sync_p.add_argument("--scope", default=None, help="Sync scope filter")
    sub.add_parser("asset-log", help="Show asset call log")
    webui_p = sub.add_parser("webui", help="Launch the WebUI dashboard")
    webui_p.add_argument("--host", default="127.0.0.1", help="Bind host")
    webui_p.add_argument("--port", type=int, default=8080, help="Bind port")
    sub.add_parser("login", help="OAuth device-code login")
    sub.add_parser("logout", help="Clear local OAuth tokens")
    hooks_p = sub.add_parser("setup-hooks", help="Install IDE hooks")
    hooks_p.add_argument("--platform", default="auto", help="IDE platform: cursor, claude-code, vscode, generic, auto")
    hooks_p.add_argument("--project-dir", default=".", help="Target project directory")
    hooks_p.add_argument("--force", action="store_true", help="Overwrite existing hook files")
    hooks_p.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    sub.add_parser("reset-local-secret", help="Reset local node secret")
    sub.add_parser("atp-complete", help="Complete an ATP task")
    sub.add_parser("buy", help="Place an ATP order")
    sub.add_parser("orders", help="List ATP orders")
    sub.add_parser("verify", help="Verify an ATP delivery")
    sub.add_parser("atp", help="ATP marketplace controls")
    sub.add_parser("recipe", help="Recipe Hub commands")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from evolver import __version__

        print(f"evolver {__version__}")
        return 0

    if args.verbose:
        os.environ["EVOLVER_VERBOSE"] = "true"

    is_loop = args.loop or args.mad_dog
    command = args.command

    # Default / run / evolve commands -> single cycle or daemon loop.
    if command in (None, "run", "/evolve") or is_loop:
        if is_loop:
            return asyncio.run(_cmd_loop(args))
        return asyncio.run(_cmd_run(args))

    if command == "solidify":
        return _cmd_solidify(args)

    if command == "fetch":
        return asyncio.run(_cmd_fetch(args))

    if command == "webui":
        return _cmd_webui(args)

    if command == "review":
        return _cmd_review(args)

    if command == "asset-log":
        return _cmd_asset_log(args)

    if command == "sync":
        return asyncio.run(_cmd_sync(args))

    if command == "distill":
        return _cmd_distill(args)

    if command == "exec":
        return _cmd_exec(args)

    if command == "setup-hooks":
        return _cmd_setup_hooks(args)

    # Placeholder for other commands.
    print(f"Command '{command}' is not yet implemented in this port.", file=sys.stderr)
    return 2


def _cmd_solidify(_args: argparse.Namespace) -> int:
    """Apply the pending solidify state."""
    from evolver.gep.solidify import solidify

    try:
        result = solidify()
    except Exception as exc:
        print(f"Solidify failed: {exc}", file=sys.stderr)
        return 1
    if result.get("ok"):
        print(f"Solidify succeeded: event_id={result.get('event_id')} blast_radius={result.get('blast_radius')}")
        return 0
    print(f"Solidify failed: {result.get('error')} details={result.get('details')}", file=sys.stderr)
    return 1


async def _cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch skills/genes/capsules from the Hub."""
    from evolver.gep.fetch import fetch_and_install

    try:
        result = await fetch_and_install(
            query=args.query or "",
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Fetch failed: {result.get('error')}", file=sys.stderr)
        return 1

    installed = result.get("installed", [])
    if not installed:
        print("No assets found.")
        return 0

    for item in installed:
        if item.get("error"):
            print(f"  SKIP {item.get('id')}: {item['error']}")
        else:
            action = "would install" if args.dry_run else "installed"
            print(f"  {action.upper()} {item.get('type')} {item.get('id')}")
    return 0


async def _cmd_run(_args: argparse.Namespace) -> int:
    """Single evolution cycle."""
    from evolver.evolve import run

    try:
        await run()
    except Exception as exc:
        print(f"Evolution failed: {exc}", file=sys.stderr)
        return 1
    return 0


async def _cmd_loop(args: argparse.Namespace) -> int:
    """Daemon loop with graceful shutdown."""
    import signal

    from evolver.evolve.runner import request_shutdown, run_loop

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_shutdown)

    try:
        await run_loop(review_mode=args.review)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0


def _cmd_webui(args: argparse.Namespace) -> int:
    """Launch the FastAPI WebUI dashboard."""
    import uvicorn

    from evolver.webui.app import app

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8080)
    print(f"Starting Evolver WebUI at http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def _cmd_review(_args: argparse.Namespace) -> int:
    """Interactive review of pending solidify state."""
    import json

    from evolver.gep.git_ops import capture_diff_snapshot, git_list_changed_files, git_list_untracked_files, is_git_repo
    from evolver.gep.paths import get_solidify_state_path, get_workspace_root
    from evolver.gep.solidify import solidify

    state_path = get_solidify_state_path()
    if not state_path.exists():
        print("No pending solidify state found.")
        return 0

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read solidify state: {exc}", file=sys.stderr)
        return 1

    last_run = state.get("last_run")
    if not last_run:
        print("No pending run to review.")
        return 0

    mutation = last_run.get("mutation") or {}
    print("=" * 60)
    print("PENDING SOLIDIFY REVIEW")
    print("=" * 60)
    print(f"Run ID:     {last_run.get('run_id')}")
    print(f"Signals:    {last_run.get('signals', [])}")
    print(f"Gene:       {last_run.get('selected_gene_id')}")
    print(f"Mutation:   {mutation.get('id')} ({mutation.get('category')})")
    print(f"Risk:       {mutation.get('risk_level', 'unknown')}")
    print(f"Validation: {mutation.get('validation', [])}")
    print("-" * 60)

    cwd = get_workspace_root()
    if is_git_repo(cwd):
        changed = git_list_changed_files(cwd)
        untracked = git_list_untracked_files(cwd)
        if changed or untracked:
            print(f"Changed files: {len(changed)}")
            print(f"Untracked files: {len(untracked)}")
            diff = capture_diff_snapshot(cwd, max_chars=2_000)
            print("\nDiff preview:")
            print(diff)
        else:
            print("No file changes detected.")
    else:
        print("Not a git repo — cannot show diff.")

    print("-" * 60)
    answer = input("Apply this solidify? [y/N/r(ollback)] ").strip().lower()
    if answer in ("y", "yes"):
        result = solidify()
        if result.get("ok"):
            print(f"Solidify succeeded: {result.get('event_id')}")
            return 0
        print(f"Solidify failed: {result.get('error')}", file=sys.stderr)
        return 1
    if answer in ("r", "rollback"):
        from evolver.gep.git_ops import rollback_new_untracked_files, rollback_tracked

        rollback_tracked()
        rollback_new_untracked_files(git_list_untracked_files(cwd))
        print("Rolled back changes.")
        return 0

    print("Aborted — solidify state preserved.")
    return 0


def _cmd_asset_log(_args: argparse.Namespace) -> int:
    """Show the asset call log (events)."""
    import json

    from evolver.gep.asset_store import read_all_events

    events = read_all_events()
    if not events:
        print("No events recorded yet.")
        return 0

    for evt in events[-20:]:
        ts = evt.get("timestamp", "?")
        gid = evt.get("gene_id", "?")
        status = (evt.get("outcome") or {}).get("status", "?")
        br = evt.get("blast_radius", {})
        print(f"{ts}  gene={gid}  status={status}  files={br.get('files', '?')}  lines={br.get('lines', '?')}")
    return 0


async def _cmd_sync(args: argparse.Namespace) -> int:
    """Sync assets with the EvoMap Hub."""
    from evolver.gep.sync import sync_all

    try:
        result = await sync_all(dry_run=args.dry_run, scope=getattr(args, "scope", None))
    except Exception as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Sync failed: {result.get('error')}", file=sys.stderr)
        return 1

    installed = result.get("installed", [])
    errors = result.get("errors", [])
    for item in installed:
        action = item.get("action", "synced")
        print(f"  {action.upper()} {item.get('type', '?')} {item.get('id', '')}")
    for err in errors:
        print(f"  ERROR: {err}")
    return 0


def _cmd_distill(args: argparse.Namespace) -> int:
    """Distill an LLM response into genes/capsules."""
    from pathlib import Path

    from evolver.gep.distill import distill_file, distill_text, install_distilled

    response_file = args.response_file
    try:
        if response_file == "-":
            text = sys.stdin.read()
            result = distill_text(text)
        else:
            result = distill_file(Path(response_file))
    except Exception as exc:
        print(f"Distill failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Distill failed: {result.get('error')}", file=sys.stderr)
        return 1

    genes = result.get("genes", [])
    capsules = result.get("capsules", [])
    mutations = result.get("mutations", [])

    print(f"Extracted: {len(genes)} gene(s), {len(capsules)} capsule(s), {len(mutations)} mutation(s)")

    install = install_distilled(result, dry_run=args.dry_run)
    for item in install.get("installed", []):
        action = item.get("action", "installed")
        print(f"  {action.upper()} {item.get('type')} {item.get('id')}")
    for err in install.get("errors", []):
        print(f"  ERROR: {err}")
    return 0


def _cmd_exec(args: argparse.Namespace) -> int:
    """Execute a command or pending validation."""
    import subprocess

    cmd = args.cmd
    if cmd:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
            print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            return proc.returncode
        except subprocess.TimeoutExpired:
            print(f"Command timed out after {args.timeout}s", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Exec failed: {exc}", file=sys.stderr)
            return 1

    # No --cmd given: try to run pending solidify validation
    import json

    from evolver.gep.paths import get_solidify_state_path

    state_path = get_solidify_state_path()
    if not state_path.exists():
        print("No pending solidify state and no --cmd provided.")
        return 0

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read solidify state: {exc}", file=sys.stderr)
        return 1

    last_run = state.get("last_run")
    if not last_run:
        print("No pending run to execute.")
        return 0

    mutation = last_run.get("mutation") or {}
    validation_commands = mutation.get("validation") or []
    if not validation_commands:
        print("No validation commands in pending mutation.")
        return 0

    print(f"Executing {len(validation_commands)} validation command(s)...")
    for vcmd in validation_commands:
        print(f"  $ {vcmd}")
        try:
            proc = subprocess.run(
                vcmd if isinstance(vcmd, list) else str(vcmd),
                shell=not isinstance(vcmd, list),
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode != 0:
                return proc.returncode
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            return 1
    return 0


def _cmd_setup_hooks(args: argparse.Namespace) -> int:
    """Install IDE hooks for the current project."""
    from evolver.adapters.setup_hooks import install_hooks

    try:
        result = install_hooks(
            platform=args.platform,
            project_dir=args.project_dir,
            force=args.force,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Setup-hooks failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Setup-hooks failed: {result.get('error')}", file=sys.stderr)
        return 1

    platform = result.get("platform", "unknown")
    print(f"Platform: {platform}")
    for msg in result.get("messages", []):
        print(f"  {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
