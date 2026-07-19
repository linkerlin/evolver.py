"""Loose-asset → Gene+Capsule bundle publish (proxy assetPublish).

Ports ``ProxyServer._assetPublish`` / ``_buildBundleFromLooseAsset`` from
Node ``proxy/index.js``. Used by ``POST /asset/submit`` and
``POST /conversation/distill``.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from typing import Any

from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id

_VALID_CATEGORIES = frozenset({"repair", "optimize", "innovate", "explore"})


def _as_text(raw: dict[str, Any]) -> str:
    return str(raw.get("content") or raw.get("summary") or "").strip()


def build_bundle_from_loose_asset(  # noqa: PLR0915
    raw: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a Hub-shaped Gene+Capsule pair from a loose MCP / distill asset."""
    r = dict(raw or {})
    # Already a full Gene: synthesise a companion Capsule from it.
    if r.get("type") == "Gene" and isinstance(r.get("strategy"), list) and r.get("id"):
        gene = dict(r)
        if not gene.get("asset_id"):
            gene["asset_id"] = compute_asset_id(gene)
        text = _as_text(gene)
        summary = str(gene.get("summary") or text[:120] or "published gene")
        signals = list(gene.get("signals_match") or ["user_request"])
        strategy = [str(s) for s in gene["strategy"] if str(s).strip()]
        capsule_body = text if len(text) >= 50 else (summary + " — " + " ".join(strategy)).strip()
        capsule = {
            "type": "Capsule",
            "schema_version": gene.get("schema_version") or SCHEMA_VERSION,
            "id": f"mcp_c_{secrets.token_hex(6)}",
            "trigger": signals,
            "gene": gene["id"],
            "summary": summary,
            "confidence": 0.5,
            "blast_radius": {"files": 1, "lines": 1},
            "content": capsule_body
            if len(capsule_body) >= 50
            else (capsule_body + " " + summary)[:80],
            "outcome": {"status": "success", "score": 0.5},
            "a2a": {"eligible_to_broadcast": True},
            "diff": "",
            "reused_asset_id": "",
            "env_fingerprint": {
                "platform": os.name,
            },
        }
        capsule["asset_id"] = compute_asset_id(capsule)
        return gene, capsule

    # Already a full Capsule: synthesise a companion Gene.
    if r.get("type") == "Capsule" and r.get("id"):
        capsule = dict(r)
        if not capsule.get("asset_id"):
            capsule["asset_id"] = compute_asset_id(capsule)
        text = _as_text(capsule)
        summary = str(capsule.get("summary") or text[:120] or "published capsule")
        signals = list(capsule.get("trigger") or ["user_request"])
        strategy = list(capsule.get("strategy") or [])
        strategy = [str(s).strip() for s in strategy if str(s).strip()]
        if len(strategy) < 2:
            strategy = [
                (summary + " — reconstruct the reusable workflow")[:200],
                "Validate the result before adopting the change",
            ]
        gene_id = str(capsule.get("gene") or f"mcp_g_{secrets.token_hex(6)}")
        gene = {
            "type": "Gene",
            "schema_version": capsule.get("schema_version") or SCHEMA_VERSION,
            "id": gene_id,
            "category": "explore",
            "summary": summary,
            "signals_match": signals,
            "strategy": strategy,
            "constraints": {"max_files": 50, "forbidden_paths": []},
            "validation": ['node -e "if (![1].length) process.exit(1)"'],
        }
        gene["asset_id"] = compute_asset_id(gene)
        capsule = dict(capsule)
        capsule["gene"] = gene_id
        capsule["asset_id"] = compute_asset_id(capsule)
        return gene, capsule

    text = _as_text(r)
    signals = (
        list(r["signals"])
        if isinstance(r.get("signals"), list) and r["signals"]
        else (
            list(r["signals_match"])
            if isinstance(r.get("signals_match"), list) and r["signals_match"]
            else ["user_request"]
        )
    )
    if isinstance(r.get("strategy"), list) and r["strategy"]:
        strategy = [str(s).strip() for s in r["strategy"] if len(str(s).strip()) >= 15]
        if len(strategy) < 2:
            raise ValueError(
                "publish: `strategy` needs >=2 steps, each >=15 chars (Hub quality gate)."
            )
    else:
        steps = [s.strip() for s in re.split(r"[.\n;]+", text) if len(s.strip()) >= 15]
        if len(steps) >= 2:
            strategy = steps[:8]
        elif len(text) >= 50:
            strategy = [text[:200], "Validate the result before adopting the change"]
        else:
            raise ValueError(
                "publish: provide `content` (>=50 chars) or a `strategy` of >=2 steps "
                "(each >=15 chars); the Hub quality-gates published genes."
            )

    category = r.get("category") if r.get("category") in _VALID_CATEGORIES else "explore"
    schema_version = r.get("schema_version") or SCHEMA_VERSION
    gid = r.get("gene_id") or f"mcp_g_{secrets.token_hex(6)}"
    summary = str(r.get("summary") or text[:120] or "manually published asset")
    capsule_content = text if len(text) >= 50 else (summary + " — " + " ".join(strategy)).strip()
    if len(capsule_content) < 50:
        raise ValueError(
            "publish: capsule content resolves to <50 chars; "
            "provide a longer `content` or `summary`."
        )

    gene: dict[str, Any] = {
        "type": "Gene",
        "schema_version": schema_version,
        "id": gid,
        "category": category,
        "summary": summary,
        "signals_match": signals,
        "strategy": strategy,
        "constraints": (
            r["constraints"]
            if isinstance(r.get("constraints"), dict)
            else {"max_files": 50, "forbidden_paths": []}
        ),
        "validation": (
            list(r["validation"])
            if isinstance(r.get("validation"), list) and r["validation"]
            else ['node -e "if (![1].length) process.exit(1)"']
        ),
    }
    gene["asset_id"] = compute_asset_id(gene)

    capsule: dict[str, Any] = {
        "type": "Capsule",
        "schema_version": schema_version,
        "id": f"mcp_c_{secrets.token_hex(6)}",
        "trigger": signals,
        "gene": gid,
        "summary": summary,
        "confidence": r["confidence"] if isinstance(r.get("confidence"), (int, float)) else 0.5,
        "blast_radius": {"files": 1, "lines": 1},
        "content": capsule_content,
        "outcome": {"status": "success", "score": 0.5},
        "a2a": {"eligible_to_broadcast": True},
        "diff": "",
        "reused_asset_id": "",
        "env_fingerprint": {"platform": os.name},
    }
    capsule["asset_id"] = compute_asset_id(capsule)
    return gene, capsule


def publish_assets(
    body: dict[str, Any],
    *,
    try_hub: bool = True,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Publish one or more loose assets as Gene+Capsule bundles.

    Best-effort Hub POST when *try_hub*; always returns a structured result so
    offline distill tests and air-gapped proxies still get a usable response.
    """
    raw_assets = body.get("assets") if isinstance(body.get("assets"), list) else None
    if raw_assets is None and body.get("asset") is not None:
        raw_assets = [body["asset"]]
    if not raw_assets:
        raise ValueError("assets is required")

    results: list[dict[str, Any]] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            results.append({"ok": False, "error": "asset must be an object"})
            continue
        try:
            gene, capsule = build_bundle_from_loose_asset(raw)
            hub_response: dict[str, Any] | None = None
            if try_hub:
                try:
                    from evolver.gep.a2a_protocol import (  # noqa: PLC0415
                        build_publish_bundle,
                        post_hub_envelope,
                    )

                    msg = build_publish_bundle(gene=gene, capsule=capsule, node_id=node_id)
                    hub_response = post_hub_envelope("/a2a/publish", msg)
                except Exception as exc:  # hub optional
                    hub_response = {"ok": False, "error": str(exc)}

            # Count as published when the bundle was built; hub is best-effort.
            results.append(
                {
                    "ok": True,
                    "gene_asset_id": gene.get("asset_id"),
                    "capsule_asset_id": capsule.get("asset_id"),
                    "response": hub_response,
                }
            )
        except ValueError as exc:
            results.append({"ok": False, "error": str(exc)})
        except Exception as exc:
            results.append({"ok": False, "error": str(exc)})

    published = sum(1 for r in results if r.get("ok"))
    return {"published": published, "total": len(results), "results": results}


def content_fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "build_bundle_from_loose_asset",
    "publish_assets",
]
