#!/usr/bin/env python3
"""Summarize recall / outcome coverage from the memory graph.

Usage:
    python scripts/recall_verify_report.py
    python scripts/recall_verify_report.py -o recall_report.md
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall verification summary")
    parser.add_argument("-o", "--output", default=None, help="Write Markdown to file")
    parser.add_argument("--signals", nargs="*", default=None, help="Probe signals for recall search")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.cognition import flatten_recall_events
    from evolver.gep.memory_graph import try_read_memory_graph_events
    from evolver.gep.recall_inject import search_recalls

    events = try_read_memory_graph_events(limit=50_000)
    flat = flatten_recall_events(events)
    kinds = Counter(str(e.get("kind", e.get("type", "unknown"))) for e in events)
    outcomes = [e for e in flat if e.get("outcome") or e.get("kind") == "outcome"]

    probe = args.signals or ["error", "pytest", "TypeError"]
    matches = search_recalls(probe, events=events, top_k=10)

    lines = [
        "# Recall verification report",
        "",
        f"- Memory graph events: **{len(events)}**",
        f"- Flattened recall rows: **{len(flat)}**",
        f"- Outcome-tagged rows: **{len(outcomes)}**",
        "",
        "## Event kinds",
    ]
    for kind, count in kinds.most_common(20):
        lines.append(f"- `{kind}`: {count}")

    lines.extend(["", f"## Recall search probe: `{probe}`", ""])
    if matches:
        for m in matches:
            lines.append(f"- similarity={m.similarity:.2f} signals={m.signals!r}")
    else:
        lines.append("_No recall matches for probe signals._")

    text = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
