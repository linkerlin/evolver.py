#!/usr/bin/env python3
"""Inspect daemon loop state and suggest recovery after a crash.

Usage:
    python scripts/recover_loop.py
    python scripts/recover_loop.py --reset-errors
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover evolver daemon loop state")
    parser.add_argument(
        "--reset-errors",
        action="store_true",
        help="Reset consecutive_errors in cycle_progress.json to 0",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import atomic_write_json, read_json_if_exists
    from evolver.gep.instance_lock import instance_lock_ctx
    from evolver.gep.paths import get_cycle_progress_path, get_solidify_state_path

    progress_path = get_cycle_progress_path()
    solidify_path = get_solidify_state_path()
    progress = read_json_if_exists(progress_path) or {}
    solidify = read_json_if_exists(solidify_path) or {}

    with instance_lock_ctx(blocking=False, timeout=0) as locked:
        lock_free = locked

    print("=== Evolver loop recovery ===")
    print(f"cycle_progress: {progress_path} ({'exists' if progress_path.exists() else 'missing'})")
    print(f"  cycle_count: {progress.get('cycle_count', 0)}")
    print(f"  consecutive_errors: {progress.get('consecutive_errors', 0)}")
    print(f"  last_timestamp: {progress.get('timestamp', 'n/a')}")
    print(f"solidify_state: {solidify_path} ({'exists' if solidify_path.exists() else 'missing'})")
    print(f"instance_lock: {'FREE' if lock_free else 'HELD (another daemon may be running)'}")

    if args.reset_errors and progress_path.exists():
        progress["consecutive_errors"] = 0
        atomic_write_json(progress_path, progress)
        print("Reset consecutive_errors to 0.")

    if not lock_free:
        print("\nSuggestion: stop the other daemon (`evolver stop`) before restarting.")
    elif progress.get("consecutive_errors", 0) > 3:
        print("\nSuggestion: inspect logs, fix root cause, then run with --reset-errors.")
    else:
        print("\nSuggestion: safe to run `uv run evolver --loop`.")

    if solidify.get("pending_review"):
        print("Note: pending solidify review — run `evolver --review` or `evolver solidify`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
