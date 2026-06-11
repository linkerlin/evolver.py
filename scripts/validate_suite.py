#!/usr/bin/env python3
"""Run integration validation: module imports + fast pytest suite.

Usage:
    python scripts/validate_suite.py
    python scripts/validate_suite.py --skip-tests
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Full local validation suite")
    parser.add_argument("--skip-tests", action="store_true", help="Only validate imports")
    parser.add_argument("--skip-imports", action="store_true", help="Only run pytest")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    scripts = repo / "scripts"

    if not args.skip_imports:
        proc = subprocess.run(
            [sys.executable, str(scripts / "validate_modules.py")],
            cwd=repo,
            check=False,
        )
        if proc.returncode != 0:
            return proc.returncode

    if not args.skip_tests:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "not slow", "-q", "--tb=no"],
            cwd=repo,
            check=False,
        )
        if proc.returncode != 0:
            return proc.returncode

    print("validate_suite: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
