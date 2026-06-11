#!/usr/bin/env python3
"""Analyze evolution events grouped by local skill directory.

Usage:
    python scripts/analyze_by_skill.py
    python scripts/analyze_by_skill.py --skill my-skill -o report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze evolution outcomes per skill")
    parser.add_argument("--skill", default=None, help="Filter to one skill id")
    parser.add_argument("-o", "--output", default=None, help="Write Markdown report")
    parser.add_argument("--limit", type=int, default=5000, help="Max events to scan")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import events_path
    from evolver.gep.paths import get_repo_root

    repo = get_repo_root() or Path.cwd()
    skills_dir = repo / "skills"
    skill_ids = []
    if skills_dir.exists():
        skill_ids = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())

    if args.skill:
        skill_ids = [args.skill] if args.skill in skill_ids or (skills_dir / args.skill).exists() else [args.skill]

    hits: dict[str, Counter[str]] = defaultdict(Counter)
    path = events_path()
    scanned = 0
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                scanned += 1
                blob = json.dumps(evt, ensure_ascii=False).lower()
                for sid in skill_ids:
                    if sid.lower() in blob:
                        hits[sid][str(evt.get("type", "unknown"))] += 1
                if scanned >= args.limit:
                    break

    lines = [
        "# Skill evolution analysis",
        "",
        f"Skills scanned: {len(skill_ids)}",
        f"Events scanned: {scanned}",
        "",
    ]
    for sid in skill_ids:
        counter = hits.get(sid, Counter())
        total = sum(counter.values())
        lines.append(f"## `{sid}`")
        lines.append(f"- Total event mentions: **{total}**")
        if counter:
            for etype, n in counter.most_common(10):
                lines.append(f"  - `{etype}`: {n}")
        else:
            lines.append("- _No matching events._")
        lines.append("")

    text = "\n".join(lines)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
