"""Main CLI entry point, equivalent to evolver/index.js."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path


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
    parser.add_argument(
        "--solo",
        action="store_true",
        help="Constrained-wild offline mode: hard-cut network/ATP/validator; implies --loop",
    )
    parser.add_argument("--review", action="store_true", help="Pause for human review")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Run one evolution cycle (default)")
    sub.add_parser("start", help="Start the evolver daemon loop")
    sub.add_parser("stop", help="Stop the evolver daemon loop")
    sub.add_parser("restart", help="Restart the evolver daemon loop")
    sub.add_parser("status", help="Show daemon status")
    log_p = sub.add_parser("log", help="Tail the evolver log")
    log_p.add_argument("--lines", type=int, default=20, help="Number of lines to show")
    sub.add_parser("check", help="Check daemon health")
    watch_p = sub.add_parser("watch", help="Run the health-watch supervisor")
    watch_p.add_argument("--once", action="store_true", help="Check once and exit")
    sub.add_parser("solidify", help="Apply pending mutation")
    sub.add_parser("review", help="Review pending solidify")
    sr_p = sub.add_parser("self-report", help="Autopoiesis self-report and rule evolution")
    sr_p.add_argument(
        "--capture",
        nargs=3,
        metavar=("CATEGORY", "DESC", "RESOLUTION"),
        help="Capture one friction point",
    )
    sr_p.add_argument("--no-write", action="store_true", help="Report only; do not persist")
    sr_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    exec_p = sub.add_parser("exec", help="Execute bridge (opt-in)")
    exec_p.add_argument("--cmd", default=None, help="Command to execute")
    exec_p.add_argument("--timeout", type=int, default=180, help="Timeout in seconds")
    distill_p = sub.add_parser("distill", help="Distill an LLM response")
    distill_p.add_argument(
        "--response-file", default="-", help="Path to response file (use - for stdin)"
    )
    distill_p.add_argument("--dry-run", action="store_true", help="Show what would be installed")
    fetch_p = sub.add_parser("fetch", help="Fetch a skill from the Hub")
    fetch_p.add_argument("query", nargs="?", default="", help="Search query or asset id")
    fetch_p.add_argument("--limit", type=int, default=5, help="Max results to fetch")
    fetch_p.add_argument("--dry-run", action="store_true", help="Show what would be installed")
    sync_p = sub.add_parser("sync", help="Sync assets with the Hub")
    sync_p.add_argument("--dry-run", action="store_true", help="Show what would be synced")
    sync_p.add_argument("--scope", default=None, help="Sync scope filter")
    sub.add_parser("asset-log", help="Show asset call log")
    replay_p = sub.add_parser("replay", help="Replay events from SQLite store")
    replay_p.add_argument("--since-id", type=int, default=0, help="Start after this row id")
    replay_p.add_argument("--limit", type=int, default=100, help="Max events to replay")
    webui_p = sub.add_parser("webui", help="Launch the WebUI dashboard")
    webui_p.add_argument("--host", default="127.0.0.1", help="Bind host")
    webui_p.add_argument("--port", type=int, default=None, help="Bind port (default: EVOLVER_WEBUI_PORT or 8080)")
    login_p = sub.add_parser("login", help="OAuth device-code login")
    login_p.add_argument("--hub-url", default=None, help="Override Hub URL")
    login_p.add_argument("--mock", action="store_true", help="Generate a mock token (dev mode)")
    sub.add_parser("logout", help="Clear local OAuth tokens")
    hooks_p = sub.add_parser("setup-hooks", help="Install IDE hooks")
    hooks_p.add_argument(
        "--platform",
        default="auto",
        help="IDE platform: cursor, claude-code, vscode, generic, codex, kiro, opencode, auto",
    )
    hooks_p.add_argument("--project-dir", default=".", help="Target project directory")
    hooks_p.add_argument("--force", action="store_true", help="Overwrite existing hook files")
    hooks_p.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    hooks_p.add_argument("--uninstall", action="store_true", help="Remove evolver runtime hooks")
    hooks_p.add_argument(
        "--verify",
        action="store_true",
        help="Verify hook installation (currently opencode)",
    )
    reset_p = sub.add_parser("reset-local-secret", help="Reset local node secret")
    reset_p.add_argument("--project-dir", default=".", help="Project directory containing .env")
    reset_p.add_argument("--also-node-id", action="store_true", help="Also regenerate A2A_NODE_ID")
    reset_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    token_p = sub.add_parser("webui-token", help="Generate or revoke WebUI tokens")
    token_p.add_argument("--generate", action="store_true", help="Create a new token")
    token_p.add_argument("--role", default="readonly", help="Token role: readonly or admin")
    token_p.add_argument("--revoke", default=None, help="Revoke a token")
    traj_p = sub.add_parser("trajectory", help="Export proxy traces into coding trajectories")
    traj_p.add_argument("--input", default=None, help="Input JSONL trace file")
    traj_p.add_argument(
        "--output", default=None, help="Output JSONL (default: <input>.trajectories.jsonl)"
    )
    traj_p.add_argument(
        "--node-secret", default=None, help="Node secret (literal) or path to a file holding it"
    )
    traj_p.add_argument(
        "--hub-private-key", default=None, help="Path to a PEM-encoded Hub private key"
    )
    traj_p.add_argument(
        "--node-secret-keyring",
        default=None,
        help='Keyring JSON mapping secret_version→secret, e.g. \'{"2":"ab..."}\'',
    )
    traj_p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Skip undecryptable rows instead of failing closed",
    )
    atp_complete_p = sub.add_parser("atp-complete", help="Complete an ATP task")
    atp_complete_p.add_argument("task_id", nargs="?", default="", help="Task ID to complete")
    buy_p = sub.add_parser("buy", help="Place an ATP order")
    buy_p.add_argument("skill_id", nargs="?", default="", help="Skill ID to purchase")
    buy_p.add_argument("--quantity", type=int, default=1, help="Order quantity")
    orders_p = sub.add_parser("orders", help="List ATP orders")
    orders_p.add_argument("--status", default=None, help="Filter by order status")
    orders_p.add_argument("--limit", type=int, default=20, help="Max orders to list")
    verify_p = sub.add_parser("verify", help="Verify an ATP delivery")
    verify_p.add_argument("order_id", nargs="?", default="", help="Order ID to verify")
    verify_p.add_argument("--reject", action="store_true", help="Reject delivery")
    atp_p = sub.add_parser("atp", help="ATP local settlement + auto-buyer controls")
    atp_sub = atp_p.add_subparsers(dest="atp_action")
    atp_sub.add_parser("balance", help="Show local settlement balance (default)")
    atp_deposit = atp_sub.add_parser("deposit", help="Credit local settlement ledger")
    atp_deposit.add_argument("amount", type=float, help="Amount to deposit")
    atp_deposit.add_argument("--reason", default="cli deposit", help="Ledger reason")
    atp_withdraw = atp_sub.add_parser("withdraw", help="Debit local settlement ledger")
    atp_withdraw.add_argument("amount", type=float, help="Amount to withdraw")
    atp_withdraw.add_argument("--reason", default="cli withdraw", help="Ledger reason")
    atp_history = atp_sub.add_parser("history", help="Show settlement transaction history")
    atp_history.add_argument("--limit", type=int, default=20, help="Max transactions")
    atp_sub.add_parser("enable", help="Enable ATP auto-buyer consent")
    atp_sub.add_parser("disable", help="Disable ATP auto-buyer consent")
    atp_sub.add_parser("status", help="Show ATP auto-buyer consent status")
    from evolver.config import PROXY_HOST, resolve_proxy_port

    proxy_p = sub.add_parser("proxy", help="Start the A2A proxy server")
    proxy_p.add_argument("--host", default=PROXY_HOST, help="Bind host")
    proxy_p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: EVOLVER_PROXY_PORT or 8081)",
    )
    recipe_p = sub.add_parser("recipe", help="Recipe Hub commands")
    recipe_sub = recipe_p.add_subparsers(dest="recipe_action")
    recipe_list = recipe_sub.add_parser("list", help="List available recipes")
    recipe_list.add_argument("--tag", default=None, help="Filter by tag")
    recipe_list.add_argument("--limit", type=int, default=20, help="Max recipes to list")
    recipe_show = recipe_sub.add_parser("show", help="Show recipe details")
    recipe_show.add_argument("recipe-id", help="Recipe ID")
    recipe_apply = recipe_sub.add_parser("apply", help="Apply a recipe")
    recipe_apply.add_argument("recipe-id", help="Recipe ID")
    recipe_apply.add_argument("--target-dir", default=".", help="Target directory")
    recipe_apply.add_argument("--dry-run", action="store_true", help="Preview without writing")
    recipe_sub.add_parser("cache-list", help="List cached recipes")
    recipe_sub.add_parser("cache-clear", help="Clear local recipe cache")

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

    is_loop = args.loop or args.mad_dog or getattr(args, "solo", False)
    command = args.command

    # Solo activation MUST happen before dispatch (and before any service reads
    # config) so the env overrides + resolve_hub_url() cut take effect at the
    # source — the "no escape valve" rule.
    if getattr(args, "solo", False):
        from evolver.solo import activate, print_solo_banner

        activate()
        print_solo_banner()

    # Default / run / evolve commands -> single cycle or daemon loop.
    if command in (None, "run", "/evolve") or is_loop:
        if is_loop:
            return asyncio.run(_cmd_loop(args))
        return asyncio.run(_cmd_run(args))

    if command == "start":
        return _cmd_start(args)
    if command == "stop":
        return _cmd_stop(args)
    if command == "restart":
        return _cmd_restart(args)
    if command == "status":
        return _cmd_status(args)
    if command == "log":
        return _cmd_log(args)
    if command == "check":
        return _cmd_check(args)
    if command == "watch":
        return _cmd_watch(args)
    if command == "solidify":
        return _cmd_solidify(args)

    if command == "self-report":
        return _cmd_self_report(args)

    if command == "fetch":
        return asyncio.run(_cmd_fetch(args))

    if command == "webui":
        return _cmd_webui(args)

    if command == "review":
        return _cmd_review(args)

    if command == "asset-log":
        return _cmd_asset_log(args)

    if command == "atp":
        return asyncio.run(_cmd_atp(args))
    if command == "replay":
        return _cmd_replay(args)

    if command == "sync":
        return asyncio.run(_cmd_sync(args))

    if command == "distill":
        return _cmd_distill(args)

    if command == "exec":
        return _cmd_exec(args)

    if command == "setup-hooks":
        return _cmd_setup_hooks(args)

    if command == "webui-token":
        return _cmd_webui_token(args)

    if command == "trajectory":
        return _cmd_trajectory(args)

    if command == "reset-local-secret":
        return _cmd_reset_local_secret(args)

    if command == "login":
        return asyncio.run(_cmd_login(args))

    if command == "logout":
        return _cmd_logout(args)

    if command == "proxy":
        return _cmd_proxy(args)

    if command == "buy":
        return asyncio.run(_cmd_buy(args))

    if command == "orders":
        return asyncio.run(_cmd_orders(args))

    if command == "verify":
        return asyncio.run(_cmd_verify(args))

    if command == "atp-complete":
        return asyncio.run(_cmd_atp_complete(args))

    if command == "recipe":
        return asyncio.run(_cmd_recipe(args))

    # Placeholder for other commands.
    print(f"Command '{command}' is not yet implemented in this port.", file=sys.stderr)
    return 2


def _cmd_start(_args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import start

    result = start()
    print(json.dumps(result.__dict__, default=str))
    return 0


def _cmd_stop(_args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import stop

    result = stop()
    print(json.dumps(result.__dict__, default=str))
    return 0


def _cmd_restart(_args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import restart

    result = restart()
    print(json.dumps(result.__dict__, default=str))
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import status

    result = status()
    data = result.__dict__.copy()
    data["processes"] = [p.__dict__ for p in result.processes]
    print(json.dumps(data, default=str, indent=2))
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import tail_log

    result = tail_log(lines=args.lines)
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    print(result.content or "")
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    import json as _json

    from evolver.ops.lifecycle import check_health, restart

    health = check_health()
    print(_json.dumps(health.__dict__, default=str, indent=2))
    if not health.healthy:
        print("[Lifecycle] Restarting...")
        res = restart()
        print(_json.dumps(res.__dict__, default=str))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    from evolver.ops.lifecycle import watch

    watch(once=args.once)
    return 0


def _cmd_solidify(_args: argparse.Namespace) -> int:
    """Apply the pending solidify state."""
    from evolver.gep.solidify import solidify

    try:
        result = solidify()
    except Exception as exc:
        print(f"Solidify failed: {exc}", file=sys.stderr)
        return 1
    if result.get("ok"):
        print(
            f"Solidify succeeded: event_id={result.get('event_id')} "
            f"blast_radius={result.get('blast_radius')}"
        )
        return 0
    print(
        f"Solidify failed: {result.get('error')} details={result.get('details')}", file=sys.stderr
    )
    return 1


def _cmd_self_report(args: argparse.Namespace) -> int:
    """Run Autopoiesis self-report (md2video harness/self_report.py equivalent)."""
    from evolver.gep.autopoiesis import run_self_report_cli

    category = description = resolution = None
    if args.capture:
        category, description, resolution = args.capture
    data = run_self_report_cli(
        category=category,
        description=description,
        resolution=resolution,
        no_write=args.no_write,
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        fs = data.get("friction_summary", {})
        evo = data.get("evolution", {})
        print(
            f"Self-report: friction={fs.get('total', 0)} "
            f"evolution_count={evo.get('evolution_count', 0)}"
        )
    return 0


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


def _cmd_trajectory(args: argparse.Namespace) -> int:  # noqa: PLR0911, PLR0912, PLR0915
    """Export proxy traces or session logs into coding trajectories (G10.1).

    Auto-detects the input kind: a Codex/Claude Code session JSONL (or a
    directory of them) is parsed as runtime sessions; otherwise the input is
    treated as proxy-trace JSONL (decrypted when ``--node-secret`` /
    ``--hub-private-key`` is given).
    """
    import json as _json
    from pathlib import Path

    from evolver.gep.trajectory import (
        build_trajectories,
        read_trace_rows,
        read_trace_rows_detailed,
        write_trajectories_to_path,
    )
    from evolver.gep.trajectory.sources import build_trajectory_from_session_log

    if not args.input:
        print("trajectory: --input <path> is required", file=sys.stderr)
        return 2
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"trajectory: input not found: {input_path}", file=sys.stderr)
        return 1
    output_path = Path(args.output) if args.output else input_path.with_suffix(".trajectories.jsonl")

    # Session-log path: a session JSONL file, or a directory of them.
    session_files: list[Path]
    if input_path.is_dir():
        session_files = sorted(input_path.rglob("*.jsonl"))
    else:
        session_files = [input_path]
    session_trajectories = []
    for sf in session_files:
        try:
            traj = build_trajectory_from_session_log(sf)
        except OSError:
            traj = None
        if traj is not None:
            session_trajectories.append(traj)

    # If every input parsed as a session log, use those directly.
    if session_trajectories and len(session_trajectories) == len(
        [f for f in session_files if f.is_file()]
    ):
        try:
            write_trajectories_to_path(output_path, session_trajectories)
        except Exception as exc:  # noqa: BLE001
            print(f"trajectory export failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"Wrote {len(session_trajectories)} session trajectory(ies) → {output_path}"
        )
        return 0

    # Otherwise: proxy-trace JSONL (single file).
    if input_path.is_dir():
        print("trajectory: input directory held no recognised session logs", file=sys.stderr)
        return 1

    node_secret = args.node_secret
    if node_secret:
        secret_path = Path(node_secret)
        if secret_path.exists() and secret_path.is_file():
            node_secret = secret_path.read_text(encoding="utf-8").strip()
    hub_private_key = None
    if args.hub_private_key:
        hub_path = Path(args.hub_private_key)
        if not hub_path.exists():
            print(f"trajectory: hub private key not found: {hub_path}", file=sys.stderr)
            return 2
        hub_private_key = hub_path.read_text(encoding="utf-8")
    keyring = None
    if args.node_secret_keyring:
        try:
            keyring = _json.loads(args.node_secret_keyring)
        except ValueError:
            print("trajectory: --node-secret-keyring must be JSON {version: secret}", file=sys.stderr)
            return 2

    try:
        if node_secret or hub_private_key or keyring:
            detailed = read_trace_rows_detailed(
                input_path,
                node_secret=node_secret,
                hub_private_key=hub_private_key,
                node_secret_keyring=keyring,
                allow_partial=args.allow_partial,
            )
            rows = detailed["rows"]
            stats = detailed["stats"]
        else:
            rows = read_trace_rows(input_path)
            stats = {"total_rows": len(rows), "encrypted_rows": 0, "decrypt_failures": 0}
        trajectories = build_trajectories(rows)
        write_trajectories_to_path(output_path, trajectories)
    except Exception as exc:  # noqa: BLE001
        print(f"trajectory export failed: {exc}", file=sys.stderr)
        return 1
    enc = stats.get("encrypted_rows", 0)
    fails = stats.get("decrypt_failures", 0)
    print(
        f"Wrote {len(trajectories)} trajectory(ies) from {stats.get('total_rows', len(rows))}"
        f" row(s) → {output_path}"
        + (f" (encrypted={enc}, skipped={fails})" if enc or fails else "")
    )
    return 0


async def _cmd_loop(args: argparse.Namespace) -> int:
    """Daemon loop with graceful shutdown."""
    import signal

    from evolver.evolve.runner import request_shutdown, run_loop

    loop = asyncio.get_running_loop()
    # Windows' ProactorEventLoop doesn't implement add_signal_handler; guard so
    # --loop/--solo work cross-platform (SIGINT still flows via KeyboardInterrupt).
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    try:
        await run_loop(review_mode=args.review)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
    return 0


def _cmd_webui(args: argparse.Namespace) -> int:
    """Launch the FastAPI WebUI dashboard."""
    import uvicorn

    from evolver.config import resolve_webui_port
    from evolver.webui.server.http import create_app

    host = getattr(args, "host", "127.0.0.1")
    port = args.port if args.port is not None else resolve_webui_port()
    print(f"Starting Evolver WebUI at http://{host}:{port}/")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0


def _cmd_review(_args: argparse.Namespace) -> int:
    """Interactive review of pending solidify state."""
    import json

    from evolver.gep.git_ops import (
        capture_diff_snapshot,
        git_list_changed_files,
        git_list_untracked_files,
        is_git_repo,
    )
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


def _cmd_replay(args: argparse.Namespace) -> int:
    from evolver.ops.sqlite_store import read_events_replay

    events = read_events_replay(args.since_id, args.limit)
    print(f"Replay {len(events)} event(s) since id={args.since_id}")
    for evt in events:
        eid = evt.get("id", "?")
        ts = evt.get("timestamp", "?")
        gid = evt.get("gene_id", "?")
        print(f"  {eid}  {ts}  {gid}")
    return 0


def _cmd_asset_log(_args: argparse.Namespace) -> int:
    """Show the asset call log (events)."""

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
        print(
            f"{ts}  gene={gid}  status={status}  "
            f"files={br.get('files', '?')}  lines={br.get('lines', '?')}"
        )
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

    print(
        f"Extracted: {len(genes)} gene(s), {len(capsules)} capsule(s), {len(mutations)} mutation(s)"
    )

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
            uninstall=args.uninstall,
            verify=args.verify,
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


def _cmd_webui_token(args: argparse.Namespace) -> int:
    from evolver.ops.auth_middleware import create_token, load_auth_db, revoke_token

    if args.revoke:
        ok = revoke_token(args.revoke)
        print("Revoked." if ok else "Token not found.")
        return 0

    if args.generate:
        token = create_token(role=args.role)
        print(f"Token ({args.role}): {token}")
        return 0

    db = load_auth_db()
    print(f"{len(db.get('tokens', {}))} token(s)")
    return 0


def _cmd_reset_local_secret(args: argparse.Namespace) -> int:
    """Reset the local A2A_NODE_SECRET."""
    from evolver.adapters.reset_secret import reset_local_secret

    try:
        result = reset_local_secret(
            project_dir=args.project_dir,
            also_node_id=args.also_node_id,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Reset failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Reset failed: {result.get('error')}", file=sys.stderr)
        return 1

    if result.get("dry_run"):
        print("DRY RUN — no files modified")
    print(f"Updated: {result['env_path']}")
    print(f"A2A_NODE_SECRET={result['secret']}")
    if result.get("node_id"):
        print(f"A2A_NODE_ID={result['node_id']}")
    return 0


async def _cmd_login(args: argparse.Namespace) -> int:
    """OAuth device-code login."""
    from evolver.adapters.auth import login

    try:
        result = await login(hub_url=args.hub_url, mock=args.mock)
    except Exception as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(f"Login failed: {result.get('error')}", file=sys.stderr)
        return 1

    print("Login successful. Token saved to ~/.evolver/auth.json")
    print(f"Expires at: {result.get('expires_at')}")
    return 0


def _cmd_logout(_args: argparse.Namespace) -> int:
    """Clear local OAuth tokens."""
    from evolver.adapters.auth import logout

    result = logout()
    if result.get("was_present"):
        print("Local auth credentials cleared.")
    else:
        print("No local auth credentials found.")
    return 0


def _cmd_proxy(args: argparse.Namespace) -> int:
    """Launch the A2A proxy server."""
    import uvicorn

    from evolver.config import resolve_proxy_port
    from evolver.proxy.server import app

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", None) or resolve_proxy_port()
    print(f"Starting Evolver A2A Proxy at http://{host}:{port}/v1/a2a/")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


async def _cmd_buy(args: argparse.Namespace) -> int:
    from evolver.atp.client import buy

    skill_id = str(getattr(args, "skill_id", "") or "").strip()
    if not skill_id:
        print("buy: skill_id is required", file=sys.stderr)
        return 2
    result = await buy(skill_id=skill_id, quantity=int(args.quantity))
    if not result.get("ok"):
        print(f"Buy failed: {result.get('error')}", file=sys.stderr)
        return 1
    print(f"Order placed: {result.get('order')}")
    return 0


async def _cmd_orders(args: argparse.Namespace) -> int:
    from evolver.atp.client import list_orders

    result = await list_orders(status=args.status, limit=args.limit)
    if not result.get("ok"):
        print(f"Orders failed: {result.get('error')}", file=sys.stderr)
        return 1
    orders = result.get("orders", [])
    print(f"{len(orders)} order(s)")
    for o in orders:
        print(f"  {o.get('id')}  {o.get('status')}  {o.get('skill_id')}")
    return 0


async def _cmd_verify(args: argparse.Namespace) -> int:
    from evolver.atp.client import verify_delivery

    order_id = str(getattr(args, "order_id", "") or "").strip()
    if not order_id:
        print("verify: order_id is required", file=sys.stderr)
        return 2
    result = await verify_delivery(order_id=order_id, approval=not args.reject)
    if not result.get("ok"):
        print(f"Verify failed: {result.get('error')}", file=sys.stderr)
        return 1
    print("Verification submitted.")
    return 0


async def _cmd_atp_complete(args: argparse.Namespace) -> int:
    from evolver.atp.client import complete_task

    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not task_id:
        print("atp-complete: task_id is required", file=sys.stderr)
        return 2
    result = await complete_task(task_id=task_id)
    if not result.get("ok"):
        print(f"Complete failed: {result.get('error')}", file=sys.stderr)
        return 1
    print("Task completed.")
    return 0


async def _cmd_atp(args: argparse.Namespace) -> int:
    from evolver.atp.settlement import credit, debit, get_balance, history

    action = args.atp_action
    if action is None or action == "balance":
        result = get_balance()
        print(f"Balance: {result['balance']}")
        return 0

    if action == "deposit":
        result = credit(args.amount, reason=args.reason)
        if not result.get("ok"):
            print(f"Deposit failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"Deposited {args.amount}. New balance: {result['balance']}")
        return 0

    if action == "withdraw":
        result = debit(args.amount, reason=args.reason)
        if not result.get("ok"):
            print(f"Withdraw failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"Withdrew {args.amount}. New balance: {result['balance']}")
        return 0

    if action == "history":
        result = history(limit=args.limit)
        for tx in result.get("transactions", []):
            print(f"{tx['timestamp']}  {tx['kind']:8}  {tx['amount']:10.4f}  {tx['reason']}")
        return 0

    if action in ("enable", "disable", "status"):
        from evolver.atp.auto_buyer import get_consent, set_consent

        if action == "status":
            consent = get_consent()
            enabled = consent.get("enabled") if consent else False
            print(f"auto_buyer: {'enabled' if enabled else 'disabled'}")
            return 0
        if action == "enable":
            set_consent(True)
            print("auto_buyer: enabled")
            return 0
        if action == "disable":
            set_consent(False)
            print("auto_buyer: disabled")
            return 0

    print(f"Unknown ATP action: {action}", file=sys.stderr)
    return 2


async def _cmd_recipe(args: argparse.Namespace) -> int:
    from evolver.recipe.client import apply_recipe, get_recipe, list_recipes

    action = args.recipe_action
    if action is None or action == "list":
        result = await list_recipes(
            tag=getattr(args, "tag", None), limit=getattr(args, "limit", 20)
        )
        if not result.get("ok"):
            print(f"Recipe list failed: {result.get('error')}", file=sys.stderr)
            return 1
        recipes = result.get("recipes", [])
        print(f"{len(recipes)} recipe(s) available")
        for r in recipes:
            print(f"  {r.get('id')}  {r.get('name', '')}")
        return 0

    if action == "show":
        rid = getattr(args, "recipe_id", getattr(args, "recipe-id", ""))
        result = await get_recipe(rid)
        if not result.get("ok"):
            print(f"Recipe show failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(result.get("recipe"))
        return 0

    if action == "apply":
        rid = getattr(args, "recipe_id", getattr(args, "recipe-id", ""))
        result = await apply_recipe(rid, target_dir=args.target_dir, dry_run=args.dry_run)
        if not result.get("ok"):
            print(f"Recipe apply failed: {result.get('error')}", file=sys.stderr)
            return 1
        if result.get("dry_run"):
            print("DRY RUN — no files modified")
        print(f"Recipe {rid} applied.")
        return 0

    if action == "cache-list":
        from evolver.recipe.cache import list_cached_recipes

        recipes = list_cached_recipes()
        print(f"{len(recipes)} cached recipe(s)")
        for r in recipes:
            print(f"  {r.get('id')}  {r.get('name', '')}")
        return 0

    if action == "cache-clear":
        from evolver.recipe.cache import clear_cache

        count = clear_cache()
        print(f"Cleared {count} cached recipe(s).")
        return 0

    print(f"Unknown recipe action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
