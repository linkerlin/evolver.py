#!/usr/bin/env python3
"""CLI shim: `python scripts/soak_env.py setup|exports|status`.

Prefer `evolver soak …`. See evolver.ops.soak_env and 演进方案.md §10.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evolver.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["soak", *sys.argv[1:]]))
