#!/usr/bin/env python3
"""Ingest A2A-compatible JSON into local GEP assets.

Usage:
    python scripts/a2a_ingest.py assets.json --mode merge
    python scripts/a2a_ingest.py assets.json --mode overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest A2A assets into local GEP store")
    parser.add_argument("input", help="Input JSON file")
    parser.add_argument("--mode", choices=["merge", "overwrite"], default="merge", help="Ingest mode")
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
    from evolver.gep.asset_store import (
        append_capsule,
        atomic_write_json,
        capsules_path,
        genes_path,
        load_capsules,
        load_genes,
        upsert_gene,
    )
    from evolver.gep.schemas.capsule import Capsule
    from evolver.gep.schemas.gene import Gene

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    incoming_genes = [g for g in data.get("genes", []) if isinstance(g, dict)]
    incoming_capsules = [c for c in data.get("capsules", []) if isinstance(c, dict)]

    if args.mode == "overwrite":
        for g in incoming_genes:
            Gene.model_validate(g)
        for c in incoming_capsules:
            Capsule.model_validate(c)
        atomic_write_json(genes_path(), {"genes": incoming_genes})
        atomic_write_json(capsules_path(), {"capsules": incoming_capsules})
        gene_count = len(incoming_genes)
        cap_count = len(incoming_capsules)
    else:
        existing_gene_ids = {g["id"] for g in load_genes() if g.get("id")}
        existing_cap_ids = {c["id"] for c in load_capsules() if c.get("id")}
        gene_count = len(existing_gene_ids)
        cap_count = len(existing_cap_ids)
        for g in incoming_genes:
            Gene.model_validate(g)
            upsert_gene(g)
            if g.get("id"):
                existing_gene_ids.add(g["id"])
        for c in incoming_capsules:
            Capsule.model_validate(c)
            if args.mode == "merge" and c.get("id") in existing_cap_ids:
                continue
            append_capsule(c)
            if c.get("id"):
                existing_cap_ids.add(c["id"])
        gene_count = len(existing_gene_ids)
        cap_count = len(existing_cap_ids)

    print(
        f"Ingested into {genes_path().parent}: "
        f"{gene_count} genes, {cap_count} capsules (mode={args.mode})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
