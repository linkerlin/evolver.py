#!/usr/bin/env python3
"""Baseline snapshot (S25.3): freeze the current evolution state for audit.

演进方案_wikiskill对照版.md §S25.3 — before changing the fitness defaults,
capture exactly what the engine looks like NOW so later claims ("the gate
improved things") have a comparable baseline.

Captures: git HEAD, effective feature flags, fitness ledger state, event
ledger statistics, bench task list. Two snapshots of the same state must be
identical apart from timestamps.

Usage:
    python scripts/baseline_snapshot.py [--output DIR]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    return (proc.stdout or "").strip()


def _pyproject_version() -> str:
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None, help="Output dir (default: baselines/<ts>)")
    args = parser.parse_args()

    from evolver.gep.feature_flags import get_all_flags
    from evolver.gep.fitness_state import load_fitness_state

    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    from evolver.gep.asset_store import read_all_events
    from evolver.gep.paths import get_gep_assets_dir

    try:
        events = read_all_events()
    except Exception:
        events = []
    statuses = Counter(str(e.get("outcome", {}).get("status")) for e in events)
    scores = [
        float(e["outcome"]["score"])
        for e in events
        if isinstance(e.get("outcome", {}).get("score"), (int, float))
    ]

    snapshot: dict[str, Any] = {
        "captured_at": captured_at,
        "git_head": _git("rev-parse", "HEAD") or "no-git",
        "pyproject_version": _pyproject_version(),
        "effective_flags": get_all_flags(),
        "fitness_ledger": load_fitness_state(),
        "events": {
            "count": len(events),
            "status_counts": dict(statuses),
            "measured_scores": sorted(scores),
            "score_mean": round(sum(scores) / len(scores), 4) if scores else None,
            "gep_assets_dir": str(get_gep_assets_dir()),
        },
    }

    out_dir = (
        Path(args.output) if args.output else ROOT / "baselines" / time.strftime("%Y%m%d-%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"baseline snapshot: {out_dir / 'snapshot.json'}")
    print(f"  git: {snapshot['git_head'][:12]}  version: {snapshot['pyproject_version']}")
    print(f"  events: {snapshot['events']['count']} ({dict(statuses)})")
    print(f"  mean measured score: {snapshot['events']['score_mean']}")
    print(f"  r_best: {snapshot['fitness_ledger'].get('r_best')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
