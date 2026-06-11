#!/usr/bin/env python3
"""Ingest A2A-compatible JSON into local GEP assets.

Usage:
    python scripts/a2a_ingest.py assets.json --mode merge
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest A2A assets into local store")
    parser.add_argument("input", help="Input JSON file")
    parser.add_argument("--mode", choices=["merge", "overwrite"], default="merge", help="Ingest mode")
    parser.add_argument("--memory-dir", default=None, help="Override memory directory")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import load_capsules, load_genes
    from evolver.gep.paths import get_memory_dir

    mem = Path(args.memory_dir) if args.memory_dir else get_memory_dir()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    existing_genes = {g["id"]: g for g in load_genes()}
    existing_capsules = {c["id"]: c for c in load_capsules()}

    for g in data.get("genes", []):
        if args.mode == "overwrite" or g["id"] not in existing_genes:
            existing_genes[g["id"]] = g

    for c in data.get("capsules", []):
        if args.mode == "overwrite" or c["id"] not in existing_capsules:
            existing_capsules[c["id"]] = c

    (mem / "genes.json").write_text(json.dumps({"genes": list(existing_genes.values())}, indent=2), encoding="utf-8")
    (mem / "capsules.json").write_text(
        json.dumps({"capsules": list(existing_capsules.values())}, indent=2), encoding="utf-8"
    )

    print(f"Ingested {len(existing_genes)} genes and {len(existing_capsules)} capsules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
