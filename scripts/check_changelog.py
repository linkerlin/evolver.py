#!/usr/bin/env python3
"""Check CHANGELOG.md presence and version alignment with pyproject.toml.

Usage:
    python scripts/check_changelog.py
    python scripts/check_changelog.py --create-stub
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _read_project_version(repo: Path) -> str:
    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("version not found in pyproject.toml")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CHANGELOG.md")
    parser.add_argument("--create-stub", action="store_true", help="Create CHANGELOG stub if missing")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    changelog = repo / "CHANGELOG.md"
    version = _read_project_version(repo)

    if not changelog.exists():
        if args.create_stub:
            changelog.write_text(
                f"# Changelog\n\n## [{version}] - Unreleased\n\n- Initial changelog stub\n",
                encoding="utf-8",
            )
            print(f"Created {changelog}")
            return 0
        print(f"Missing CHANGELOG.md (project version {version})", file=sys.stderr)
        print("Run with --create-stub to generate a template.", file=sys.stderr)
        return 1

    body = changelog.read_text(encoding="utf-8")
    if version not in body:
        print(f"WARNING: version {version} not mentioned in CHANGELOG.md", file=sys.stderr)
        return 1

    print(f"OK: CHANGELOG.md references version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
