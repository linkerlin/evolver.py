#!/usr/bin/env python3
"""Generate a Markdown timeline from GEP evolution events.

Usage:
    python scripts/generate_history.py -o history.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def _read_events(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(events) >= limit:
                break
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="GEP evolution history (Markdown)")
    parser.add_argument("-o", "--output", default="evolution_history.md")
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import events_path

    events = _read_events(events_path(), args.limit)
    types = Counter(str(e.get("type", "unknown")) for e in events)

    lines = [
        "# Evolution history",
        "",
        f"Generated: {datetime.now().isoformat()}",
        f"Events loaded: {len(events)}",
        "",
        "## By type",
    ]
    for t, n in types.most_common():
        lines.append(f"- `{t}`: {n}")

    lines.append("\n## Timeline (latest 80)\n")
    for evt in events[-80:]:
        ts = evt.get("timestamp")
        when = (
            datetime.fromtimestamp(ts).isoformat(timespec="seconds")
            if isinstance(ts, (int, float))
            else str(ts or "?")
        )
        etype = evt.get("type", "event")
        gene = evt.get("gene_id") or evt.get("mutation", {}).get("gene_id")
        extra = f" gene={gene}" if gene else ""
        lines.append(f"- **{when}** `{etype}`{extra}")

    out = Path(args.output)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(events)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
