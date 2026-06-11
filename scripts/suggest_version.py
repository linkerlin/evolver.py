#!/usr/bin/env python3
"""Suggest next semantic version from recent git commits.

Usage:
    python scripts/suggest_version.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _parse_version(raw: str) -> tuple[int, int, int]:
    parts = raw.split(".")
    while len(parts) < 3:
        parts.append("0")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _bump(version: str, kind: str) -> str:
    major, minor, patch = _parse_version(version)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest semantic version bump")
    parser.add_argument("--commits", type=int, default=50, help="Commits to inspect")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    pyproject = repo / "pyproject.toml"
    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        print("Could not read version from pyproject.toml", file=sys.stderr)
        return 1
    current = match.group(1)

    proc = subprocess.run(
        ["git", "log", f"-{args.commits}", "--pretty=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr or "git log failed", file=sys.stderr)
        return 1

    bump = "patch"
    for subject in proc.stdout.splitlines():
        lower = subject.lower()
        if "breaking" in lower or "!" in subject:
            bump = "major"
            break
        if lower.startswith("feat") or lower.startswith("feature"):
            bump = "minor"

    suggested = _bump(current, bump)
    print(f"current:   {current}")
    print(f"suggested: {suggested} ({bump} bump)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
