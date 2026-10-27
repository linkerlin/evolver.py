"""Distill an LLM response into a Gene or Capsule.

Equivalent to evolver/src/gep/distill.js.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

from evolver.gep.asset_store import append_capsule, upsert_gene
from evolver.gep.content_hash import compute_asset_id
from evolver.gep.schemas.capsule import Capsule
from evolver.gep.schemas.gene import Gene

DISTILL_FORMAT_HINT: Final = (
    "no GEP assets extracted: submit the dispatch prompt's required ```json asset "
    'blocks, e.g. {"type": "Gene", "id": "gene_<slug>", "category": '
    '"repair|optimize|innovate|explore", "summary": "...", "signals_match": [...], '
    '"strategy": [...], "validation": [...]}; free-text summaries are not distilled'
)


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects from a text, handling fenced code blocks."""
    blocks: list[dict[str, Any]] = []
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


def _is_valid_gep_asset(obj: dict[str, Any]) -> bool:
    return obj.get("type") in ("Gene", "Capsule", "Mutation")


def distill_text(text: str) -> dict[str, Any]:
    """Parse *text* and return extracted GEP assets.

    Returns a dict with ``genes``, ``capsules``, ``mutations`` lists.
    """
    blocks = _extract_json_blocks(text)
    genes: list[dict[str, Any]] = []
    capsules: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
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


def filter_confounded_distillation(
    result: dict[str, Any],
    attribution: dict[str, Any] | None = None,
    *,
    strict_transferable: bool = False,
) -> dict[str, Any]:
    """Filter out durable gene candidates from confounded rounds or with workspace leaks.

    Harness2 (§3.2) ``NO_ENTRY`` rule: when a round's attribution is ``confounded``
    (or ``eligible_for_experience`` is ``False``), durable experience entries must
    not be written into the library. When ``strict_transferable=True``, each gene
    is also checked against :func:`validate_transferable_experience`.
    """
    from evolver.gep.skill2gep_audit import validate_transferable_experience

    genes = list(result.get("genes", []))
    kept_genes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    is_confounded = isinstance(attribution, dict) and (
        bool(attribution.get("confounded")) or attribution.get("eligible_for_experience") is False
    )

    for gene in genes:
        if is_confounded:
            skipped.append(
                {
                    "id": gene.get("id"),
                    "reason": "confounded_or_ineligible_attribution",
                    "status": attribution.get("status") if isinstance(attribution, dict) else None,
                }
            )
            continue
        if strict_transferable:
            verdict = validate_transferable_experience(gene, attribution=attribution)
            if not verdict["ok"] or verdict.get("no_entry"):
                skipped.append(
                    {
                        "id": gene.get("id"),
                        "reason": verdict["reason"],
                        "steer_message": verdict.get("steer_message", ""),
                    }
                )
                continue
        kept_genes.append(gene)

    filtered = dict(result)
    filtered["genes"] = kept_genes
    filtered["skipped_genes"] = skipped
    return filtered


def install_distilled(
    result: dict[str, Any],
    *,
    dry_run: bool = False,
    attribution: dict[str, Any] | None = None,
    strict_transferable: bool = False,
) -> dict[str, Any]:
    """Install distilled genes and capsules into the local asset store."""
    filtered = filter_confounded_distillation(
        result,
        attribution=attribution,
        strict_transferable=strict_transferable,
    )
    installed: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped_genes: list[dict[str, Any]] = list(filtered.get("skipped_genes", []))

    for gene in filtered.get("genes", []):
        if dry_run:
            installed.append({"id": gene.get("id"), "type": "Gene", "action": "would_install"})
            continue
        try:
            gene["asset_id"] = compute_asset_id(gene)
            upsert_gene(gene)
            installed.append({"id": gene["id"], "type": "Gene", "asset_id": gene["asset_id"]})
        except Exception as exc:
            errors.append(f"gene {gene.get('id')}: {exc}")

    for cap in filtered.get("capsules", []):
        if dry_run:
            installed.append({"id": cap.get("id"), "type": "Capsule", "action": "would_install"})
            continue
        try:
            cap["asset_id"] = compute_asset_id(cap)
            append_capsule(cap)
            installed.append({"id": cap["id"], "type": "Capsule", "asset_id": cap["asset_id"]})
        except Exception as exc:
            errors.append(f"capsule {cap.get('id')}: {exc}")

    out: dict[str, Any] = {
        "ok": len(errors) == 0,
        "installed": installed,
        "errors": errors,
    }
    if skipped_genes:
        out["skipped_genes"] = skipped_genes
    return out


def distill_file(path: Path) -> dict[str, Any]:
    """Distill a response file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return distill_text(text)
