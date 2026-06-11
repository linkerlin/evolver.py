#!/usr/bin/env python3
"""Seed local ATP merchant service definitions and optional ledger credit.

Usage:
    python scripts/seed_merchants.py
    python scripts/seed_merchants.py --credit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ATP merchant services locally")
    parser.add_argument("--credit", type=float, default=0.0, help="Ledger credit amount")
    parser.add_argument("--output", "-o", default=None, help="Write services JSON path")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.atp.default_handler import resolve_atp_services
    from evolver.atp.settlement import credit
    from evolver.gep.paths import get_memory_dir

    services = resolve_atp_services()
    out = Path(args.output) if args.output else get_memory_dir() / "atp_services_seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"services": services}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(services)} service(s) to {out}")

    if args.credit > 0:
        result = credit(args.credit, reason="seed_merchants.py")
        if not result.get("ok"):
            print(f"Credit failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"Credited ledger: {args.credit}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
