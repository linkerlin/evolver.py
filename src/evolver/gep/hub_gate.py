"""Hub quality gate — review/verify orchestration for pipeline + WebUI."""

from __future__ import annotations

from typing import Any

from evolver.gep.content_hash import verify_asset_id
from evolver.gep.hub_review import review_service_listing
from evolver.gep.hub_verify import verify_service_schema


def _review_dict(result: Any) -> dict[str, Any]:
    return {
        "verdict": result.verdict.value,
        "score": result.score,
        "summary": result.summary,
        "comments": [
            {
                "severity": c.severity,
                "message": c.message,
                "line": c.line,
                "file": c.file,
            }
            for c in result.comments
        ],
    }


def _verify_dict(result: Any) -> dict[str, Any]:
    def _c(comment: Any) -> dict[str, Any]:
        return {
            "severity": comment.severity,
            "message": comment.message,
            "line": comment.line,
            "file": comment.file,
        }

    return {
        "valid": result.valid,
        "errors": [_c(c) for c in result.errors],
        "warnings": [_c(c) for c in result.warnings],
    }


def gate_service(service: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_id": service.get("service_id"),
        "verify": _verify_dict(verify_service_schema(service)),
        "review": _review_dict(review_service_listing(service)),
    }


def gate_hub_services(
    hits: list[dict[str, Any]],
    services: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {
        str(s.get("service_id")): s
        for s in services
        if isinstance(s, dict) and s.get("service_id")
    }
    gated: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        service = by_id.get(str(hit.get("service_id", "")))
        if not service:
            continue
        entry = gate_service(service)
        entry["hub_score"] = hit.get("score")
        gated.append(entry)
    return gated


def gate_hub_asset(asset: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "asset_id": asset.get("asset_id"),
        "type": asset.get("type"),
        "summary": asset.get("summary"),
    }
    asset_id = asset.get("asset_id")
    if isinstance(asset_id, str) and asset_id.startswith("sha256:") and len(asset) > 2:
        entry["hash_valid"] = verify_asset_id(asset, asset_id)
    return entry


def enrich_hub_quality(ctx: dict[str, Any]) -> dict[str, Any]:
    hub_response = ctx.get("hub_response")
    services = hub_response.get("services", []) if isinstance(hub_response, dict) else []
    return {
        "services": gate_hub_services(ctx.get("hub_service_hits") or [], services),
        "assets": [gate_hub_asset(a) for a in (ctx.get("hub_assets") or []) if isinstance(a, dict)],
    }


def verdict_label(verdict: str) -> str:
    return {"approve": "通过", "revise": "需修订", "reject": "拒绝"}.get(verdict, verdict)
