#!/usr/bin/env python3
"""Promote a candidate gene from candidates.jsonl into the active gene store.

Usage:
    python scripts/a2a_promote.py --latest
    python scripts/a2a_promote.py --id gene-candidate-1
    python scripts/a2a_promote.py --latest --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _extract_gene(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if candidate.get("type") == "Gene":
        return candidate
    nested = candidate.get("gene")
    if isinstance(nested, dict):
        return nested
    if candidate.get("id") and candidate.get("category"):
        return candidate
    return None


def _pick_candidate(candidates: list[dict[str, Any]], gene_id: str | None, latest: bool) -> dict[str, Any] | None:
    if gene_id:
        for row in reversed(candidates):
            gene = _extract_gene(row)
            if row.get("id") == gene_id or (gene and gene.get("id") == gene_id):
                return row
        return None
    if latest and candidates:
        return candidates[-1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote candidate gene to active store")
    parser.add_argument("--id", default=None, help="Candidate or gene id")
    parser.add_argument("--latest", action="store_true", help="Promote newest candidate")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not write")
    args = parser.parse_args()

    if not args.id and not args.latest:
        print("Specify --id or --latest", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import append_event_jsonl, read_recent_candidates, upsert_gene
    from evolver.gep.schemas.gene import Gene, validate_gene

    candidates = read_recent_candidates(limit=500)
    row = _pick_candidate(candidates, args.id, args.latest)
    if row is None:
        print("Candidate not found", file=sys.stderr)
        return 1

    gene_data = _extract_gene(row)
    if gene_data is None:
        print("Candidate does not contain a Gene payload", file=sys.stderr)
        return 1

    try:
        gene = Gene.model_validate(gene_data)
        validate_gene(gene)
    except Exception as exc:
        print(f"Gene validation failed: {exc}", file=sys.stderr)
        return 1

    payload = gene.model_dump()
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "gene_id": payload.get("id")}, indent=2))
        return 0

    upsert_gene(payload)
    append_event_jsonl(
        {
            "type": "gene_promoted",
            "timestamp": time.time(),
            "gene_id": payload.get("id"),
            "source": "a2a_promote.py",
        }
    )
    print(f"Promoted gene {payload.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
