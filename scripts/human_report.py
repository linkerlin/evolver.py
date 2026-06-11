#!/usr/bin/env python3
"""Convert events.jsonl into a human-readable Markdown report.

Usage:
    python scripts/human_report.py --output report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate human-readable evolution report")
    parser.add_argument("--memory-dir", default=None, help="Override memory directory")
    parser.add_argument("--output", "-o", default="evolution_report.md", help="Output Markdown file")
    parser.add_argument("--limit", type=int, default=500, help="Max events")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.paths import get_memory_dir

    mem = Path(args.memory_dir) if args.memory_dir else get_memory_dir()
    events_path = mem / "events.jsonl"

    events = []
    if events_path.exists():
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= args.limit:
                    break

    lines = [
        "# Evolution Report",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"Total events: {len(events)}\n",
        "## Summary",
        f"- Cycle starts: {sum(1 for e in events if e.get('type') == 'cycle_start')}",
        f"- Cycle ends: {sum(1 for e in events if e.get('type') == 'cycle_end')}",
        f"- Solidifies: {sum(1 for e in events if e.get('type') == 'solidify')}",
        f"- Errors: {sum(1 for e in events if 'error' in str(e).lower())}",
        "\n## Recent Events",
    ]

    for evt in events[-100:]:
        ts = evt.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts).isoformat() if ts else "unknown"
        lines.append(f"\n### {evt.get('type', 'event')} @ {dt}")
        for k, v in evt.items():
            if k in ("type", "timestamp"):
                continue
            lines.append(f"- **{k}**: {v}")

    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {args.output} ({len(events)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
