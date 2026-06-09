"""Canary script: verify evolver CLI loads without crashing.

Equivalent to evolver/src/canary.js.
Run in a forked child process before solidify commits an evolution.
Exit 0 = safe, non-zero = broken.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        # Import the CLI module to verify it loads cleanly.
        import evolver.cli  # noqa: F401

        return 0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:500]
        sys.stderr.write(msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())
