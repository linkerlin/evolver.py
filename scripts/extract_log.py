#!/usr/bin/env python3
"""Extract specific time ranges or signal types from events.jsonl.

Usage:
    python scripts/extract_log.py --since 2026-01-01 --type error
    python scripts/extract_log.py --signal plateau
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract events from events.jsonl")
    parser.add_argument("--memory-dir", default=None, help="Override memory directory")
    parser.add_argument("--since", default=None, help="ISO date lower bound (e.g. 2026-01-01)")
    parser.add_argument("--until", default=None, help="ISO date upper bound")
    parser.add_argument("--type", default=None, help="Event type filter")
    parser.add_argument("--signal", default=None, help="Signal substring filter")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows")
    parser.add_argument("--output", "-o", default=None, help="Output file (default stdout)")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.paths import get_memory_dir

    mem = Path(args.memory_dir) if args.memory_dir else get_memory_dir()
    events_path = mem / "events.jsonl"

    since_ts = datetime.fromisoformat(args.since).timestamp() if args.since else None
    until_ts = datetime.fromisoformat(args.until).timestamp() if args.until else None

    results = []
    if events_path.exists():
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = evt.get("timestamp", 0)
                if since_ts is not None and ts < since_ts:
                    continue
                if until_ts is not None and ts > until_ts:
                    continue
                if args.type and evt.get("type") != args.type:
                    continue
                if args.signal and args.signal not in str(evt.get("signals", [])):
                    continue
                results.append(evt)
                if len(results) >= args.limit:
                    break

    out = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Wrote {len(results)} events to {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
