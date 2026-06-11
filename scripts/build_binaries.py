#!/usr/bin/env python3
"""Build a standalone evolver executable (PyInstaller when available).

Usage:
    python scripts/build_binaries.py
    python scripts/build_binaries.py --output dist/evolver.exe
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evolver standalone binary")
    parser.add_argument("--output", "-o", default=None, help="Output binary path")
    parser.add_argument("--check-only", action="store_true", help="Only verify toolchain")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    entry = repo / "src" / "evolver" / "cli.py"
    if not entry.exists():
        print(f"Missing entrypoint: {entry}", file=sys.stderr)
        return 1

    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("PyInstaller not found. Install with:", file=sys.stderr)
        print("  uv pip install pyinstaller", file=sys.stderr)
        print("\nSuggested command after install:", file=sys.stderr)
        print(
            f"  pyinstaller --onefile --name evolver {entry}",
            file=sys.stderr,
        )
        return 1 if not args.check_only else 0

    if args.check_only:
        print(f"OK: pyinstaller at {pyinstaller}")
        return 0

    dist_name = "evolver"
    out_dir = repo / "dist"
    cmd = [
        pyinstaller,
        "--onefile",
        "--name",
        dist_name,
        "--paths",
        str(repo / "src"),
        str(entry),
    ]
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=repo, check=False)
    if proc.returncode != 0:
        return proc.returncode

    built = out_dir / (dist_name + (".exe" if sys.platform == "win32" else ""))
    if args.output and built.exists():
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, dest)
        print(f"Copied to {dest}")
    elif built.exists():
        print(f"Built {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
