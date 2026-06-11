#!/usr/bin/env python3
"""Export local GEP assets to A2A-compatible JSON format.

Usage:
    python scripts/a2a_export.py --output assets.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export GEP assets to A2A format")
    parser.add_argument("--output", "-o", required=True, help="Output JSON file")
    parser.add_argument(
        "--gep-assets-dir",
        default=None,
        help="Override GEP_ASSETS_DIR (default: workspace .evolver/gep)",
    )
    args = parser.parse_args()

    if args.gep_assets_dir:
        import os

        os.environ["GEP_ASSETS_DIR"] = str(Path(args.gep_assets_dir).resolve())

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import load_capsules, load_genes, genes_path

    payload = {
        "version": "1.0",
        "genes": load_genes(),
        "capsules": load_capsules(),
    }

    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Exported {len(payload['genes'])} genes and {len(payload['capsules'])} capsules "
        f"from {genes_path().parent} to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
