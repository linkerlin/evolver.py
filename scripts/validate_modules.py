#!/usr/bin/env python3
"""Validate that all evolver modules import correctly.

Usage:
    python scripts/validate_modules.py
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from pathlib import Path


def walk_modules(package_name: str):
    try:
        package = importlib.import_module(package_name)
    except Exception as exc:
        print(f"FAIL {package_name}: {exc}")
        return 1
    prefix = package.__name__ + "."
    errors = 0
    for _, modname, ispkg in pkgutil.walk_packages(package.__path__, prefix):
        try:
            importlib.import_module(modname)
            print(f"OK   {modname}")
        except Exception as exc:
            print(f"FAIL {modname}: {exc}")
            errors += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate module imports")
    parser.add_argument("--package", default="evolver", help="Top-level package to validate")
    args = parser.parse_args()

    src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(src))

    errors = walk_modules(args.package)
    if errors:
        print(f"\n{errors} module(s) failed to import")
        return 1
    print("\nAll modules imported successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
