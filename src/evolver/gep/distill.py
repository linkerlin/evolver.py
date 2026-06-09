"""Distill an LLM response into a Gene or Capsule.

Equivalent to evolver/src/gep/distill.js.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.gep.asset_store import append_capsule, upsert_gene
from evolver.gep.content_hash import compute_asset_id
from evolver.gep.schemas.capsule import Capsule
from evolver.gep.schemas.gene import Gene


def _extract_json_blocks(text: str) -> list[dict]:
    """Extract JSON objects from a text, handling fenced code blocks."""
    blocks: list[dict] = []
    # Try fenced code blocks first
    for match in re.finditer(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL):
        inner = match.group(1).strip()
        try:
            obj = json.loads(inner)
            if isinstance(obj, dict):
                blocks.append(obj)
        except json.JSONDecodeError:
            pass
    # Fallback: bare JSON objects
    if not blocks:
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL):
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict):
                    blocks.append(obj)
            except json.JSONDecodeError:
                pass
    return blocks


def _is_valid_gep_asset(obj: dict) -> bool:
    return obj.get("type") in ("Gene", "Capsule", "Mutation")


def distill_text(text: str) -> dict[str, Any]:
    """Parse *text* and return extracted GEP assets.

    Returns a dict with ``genes``, ``capsules``, ``mutations`` lists.
    """
    blocks = _extract_json_blocks(text)
    genes: list[dict] = []
    capsules: list[dict] = []
    mutations: list[dict] = []
    errors: list[str] = []

    for obj in blocks:
        if not _is_valid_gep_asset(obj):
            continue
        asset_type = obj.get("type")
        try:
            if asset_type == "Gene":
                gene = Gene.model_validate(obj)
                genes.append(gene.model_dump())
            elif asset_type == "Capsule":
                cap = Capsule.model_validate(obj)
                capsules.append(cap.model_dump())
            elif asset_type == "Mutation":
                mutations.append(obj)
        except Exception as exc:
            errors.append(str(exc))

    return {
        "ok": True,
        "genes": genes,
        "capsules": capsules,
        "mutations": mutations,
        "errors": errors,
    }


def install_distilled(result: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Install distilled genes and capsules into the local asset store."""
    installed: list[dict] = []
    errors: list[str] = []

    for gene in result.get("genes", []):
        if dry_run:
            installed.append({"id": gene.get("id"), "type": "Gene", "action": "would_install"})
            continue
        try:
            gene["asset_id"] = compute_asset_id(gene)
            upsert_gene(gene)
            installed.append({"id": gene["id"], "type": "Gene", "asset_id": gene["asset_id"]})
        except Exception as exc:
            errors.append(f"gene {gene.get('id')}: {exc}")

    for cap in result.get("capsules", []):
        if dry_run:
            installed.append({"id": cap.get("id"), "type": "Capsule", "action": "would_install"})
            continue
        try:
            cap["asset_id"] = compute_asset_id(cap)
            append_capsule(cap)
            installed.append({"id": cap["id"], "type": "Capsule", "asset_id": cap["asset_id"]})
        except Exception as exc:
            errors.append(f"capsule {cap.get('id')}: {exc}")

    return {
        "ok": len(errors) == 0,
        "installed": installed,
        "errors": errors,
    }


def distill_file(path: Path) -> dict[str, Any]:
    """Distill a response file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return distill_text(text)
