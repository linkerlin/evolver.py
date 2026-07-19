"""Asset normalization utilities — model ID canonicalization, preview formatting.

Equivalent to ``evolver/src/gep/assets.js``.
Provides model ID canonicalization (Anthropic → Bedrock) and asset preview
formatting for CLI/log output.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Model ID canonicalization
# ---------------------------------------------------------------------------

BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-3-7-sonnet-20250219": "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-3-5-sonnet-20241022": "anthropic.claude-3-5-sonnet-20241022-v1:0",
    "claude-3-5-sonnet-20240620": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "claude-3-opus-20240229": "anthropic.claude-3-opus-20240229-v1:0",
    "claude-3-sonnet-20240229": "anthropic.claude-3-sonnet-20240229-v1:0",
    "claude-3-haiku-20240307": "anthropic.claude-3-haiku-20240307-v1:0",
}


def canonicalize_model(model_id: str) -> str:
    """Convert Anthropic model ID to Bedrock model ID.

    Returns the original ID if no mapping exists.
    """
    return BEDROCK_MODEL_MAP.get(model_id, model_id)


# Backward-compatible alias
canonicalize_for_bedrock = canonicalize_model


# ---------------------------------------------------------------------------
# Asset preview formatting
# ---------------------------------------------------------------------------


def format_gene_preview(gene: dict[str, Any]) -> str:
    """Return a one-line preview of a gene for CLI/log output."""
    gid = gene.get("id", "?")
    category = gene.get("category", "?")
    risk = gene.get("risk_level", "?")
    score = gene.get("score", "?")
    summary = gene.get("summary", "")
    parts = [f"[{risk}] {gid} ({category})"]
    if score != "?":
        parts.append(f"score={score}")
    if summary:
        parts.append(f"— {summary[:80]}")
    return " ".join(parts)


def format_capsule_preview(capsule: dict[str, Any]) -> str:
    """Return a one-line preview of a capsule for CLI/log output."""
    cid = capsule.get("id", "?")
    ctype = capsule.get("type", "?")
    source = capsule.get("source", "?")
    gene_id = capsule.get("gene_id", "?")
    return f"{cid} ({ctype}) ← gene={gene_id} source={source}"


def format_asset_list(assets: list[dict[str, Any]], *, asset_type: str = "gene") -> str:
    """Return a formatted list of assets for CLI output."""
    if not assets:
        return f"No {asset_type}s found."
    formatter = format_gene_preview if asset_type == "gene" else format_capsule_preview
    lines = [f"{len(assets)} {asset_type}(s):"]
    for i, asset in enumerate(assets[:20]):
        lines.append(f"  {i + 1:3d}. {formatter(asset)}")
    if len(assets) > 20:
        lines.append(f"  ... and {len(assets) - 20} more")
    return "\n".join(lines)


def truncate_asset_id(asset_id: str, *, length: int = 12) -> str:
    """Truncate a long sha256: asset ID to a short readable form."""
    if not asset_id:
        return "?"
    if asset_id.startswith("sha256:"):
        short = asset_id[7:]
        return "sha256:" + short[:length] + ("…" if len(short) > length else "")
    if len(asset_id) > length:
        return asset_id[:length] + "…"
    return asset_id
