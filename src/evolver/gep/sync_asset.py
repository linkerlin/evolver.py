"""Normalize Hub assets for local install (sync pipeline).

Equivalent to ``evolver/src/gep/syncAsset.js`` — behaviour reconstructed from
the readable ``syncAsset.test.js`` contract (v1.92.0).

Hub payloads are allow-list copied (no prototype pollution), validated for
contract fields, stamped with ``hub_asset_id`` / ``synced_at``, then
re-hashed so the local ``asset_id`` reflects the installed content.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id
from evolver.gep.schemas.capsule import (
    VALID_COST_TIERS,
    VALID_OUTCOME_STATUSES,
    VALID_VISIBILITIES,
)
from evolver.gep.schemas.gene import (
    VALID_CATEGORIES,
    VALID_REASONING_LEVELS,
    VALID_ROUTING_TIERS,
    VALID_TOOL_POLICY_SEVERITIES,
)

# Hub-only category accepted by prepareSyncAsset but NOT by standard Gene APIs.
HUB_GENE_CATEGORIES = [*VALID_CATEGORIES, "regulatory"]

_GENE_ARRAY_FIELDS = (
    "signals_match",
    "strategy",
    "validation",
    "preconditions",
    "anti_patterns",
    "postconditions",
)

_GENE_OPTIONAL_SCALAR = (
    "trigger",
    "parent",
    "summary",
    "schema_version",
    "anti_pattern",
    "failure_reason",
    "model_name",
    "domain",
)

_GENE_OPTIONAL_OBJECT = (
    "constraints",
    "routing_hint",
    "tool_policy",
    "metadata",
    "performance_metrics",
)

_GENE_OPTIONAL_LIST_OF_OBJ = (
    "epigenetic_marks",
    "learning_history",
)

_CAPSULE_COPY_FIELDS = (
    "schema_version",
    "trigger",
    "gene",
    "genes_used",
    "summary",
    "confidence",
    "blast_radius",
    "outcome",
    "env_fingerprint",
    "success_streak",
    "success_reason",
    "source_type",
    "reused_asset_id",
    "a2a",
    "strategy",
    "execution_trace",
    "visibility",
    "scope",
    "cost_tier",
    "pack_of",
    "author",
    "parent",
    "validation",
    "code_snippet",
    "content",
    "diff",
    "preconditions",
    "postconditions",
    "metadata",
    "performance_metrics",
    "capsule_id",
    "failure_reason",
    "diff_snapshot",
    "lesson_learned",
    "model_name",
    "trigger_context",
    "skills_used",
    "domain",
)


def _is_plain_object(value: Any) -> bool:
    return isinstance(value, dict) and not isinstance(value, type)


def _require_string(prefix: str, field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{field} must be a string")
    return value


def _require_array(prefix: str, field: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{prefix}.{field} must be an array")
    return value


def _optional_string(prefix: str, field: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{field} must be a string")
    return value


def _validate_gene_payload(payload: dict[str, Any]) -> None:  # noqa: PLR0912, SIM102
    if "signals_match" not in payload or not isinstance(payload.get("signals_match"), list):
        raise ValueError("Gene.signals_match must be an array")

    if "strategy" in payload and payload["strategy"] is not None:
        if not isinstance(payload["strategy"], list):
            raise ValueError("Gene.strategy must be an array")

    if "constraints" in payload and payload["constraints"] is not None:
        if not _is_plain_object(payload["constraints"]):
            raise ValueError("Gene.constraints must be an object")

    if "routing_hint" in payload and payload["routing_hint"] is not None:
        rh = payload["routing_hint"]
        if not _is_plain_object(rh):
            raise ValueError("Gene.routing_hint must be an object")
        tier = rh.get("tier")
        if tier is not None and tier not in VALID_ROUTING_TIERS:
            raise ValueError(
                f"Gene.routing_hint.tier must be one of: {', '.join(VALID_ROUTING_TIERS)}"
            )
        level = rh.get("reasoning_level")
        if level is not None and level not in VALID_REASONING_LEVELS:
            raise ValueError(
                "Gene.routing_hint.reasoning_level must be one of: "
                + ", ".join(VALID_REASONING_LEVELS)
            )

    if "tool_policy" in payload and payload["tool_policy"] is not None:
        tp = payload["tool_policy"]
        if not _is_plain_object(tp):
            raise ValueError("Gene.tool_policy must be an object")
        sev = tp.get("severity")
        if sev is not None and sev not in VALID_TOOL_POLICY_SEVERITIES:
            raise ValueError(
                "Gene.tool_policy.severity must be one of: "
                + ", ".join(VALID_TOOL_POLICY_SEVERITIES)
            )

    if "trigger" in payload and payload["trigger"] is not None:
        if not isinstance(payload["trigger"], str):
            raise ValueError("Gene.trigger must be a string")

    category = payload.get("category")
    if category is not None and category not in HUB_GENE_CATEGORIES:
        raise ValueError(
            f"Gene.category must be one of: {', '.join(HUB_GENE_CATEGORIES)}, got: {category}"
        )


def _validate_capsule_payload(payload: dict[str, Any]) -> None:  # noqa: PLR0912, SIM102
    outcome = payload.get("outcome")
    if not _is_plain_object(outcome):
        raise ValueError("Capsule.outcome must be an object")
    status = outcome.get("status") if outcome else None
    if status not in VALID_OUTCOME_STATUSES:
        raise ValueError(
            "Capsule.outcome.status must be one of: " + ", ".join(VALID_OUTCOME_STATUSES)
        )

    if "trigger" in payload and payload["trigger"] is not None:
        if not isinstance(payload["trigger"], list):
            raise ValueError("Capsule.trigger must be an array")

    if "execution_trace" in payload and payload["execution_trace"] is not None:
        if not isinstance(payload["execution_trace"], list):
            raise ValueError("Capsule.execution_trace must be an array")

    if "visibility" in payload and payload["visibility"] is not None:
        if payload["visibility"] not in VALID_VISIBILITIES:
            raise ValueError("Capsule.visibility must be one of: " + ", ".join(VALID_VISIBILITIES))

    if "cost_tier" in payload and payload["cost_tier"] is not None:
        if payload["cost_tier"] not in VALID_COST_TIERS:
            raise ValueError("Capsule.cost_tier must be one of: " + ", ".join(VALID_COST_TIERS))

    if "source_type" in payload and payload["source_type"] is not None:
        st = payload["source_type"]
        if not isinstance(st, str) or not st or len(st) > 128 or st != st.strip() or "\n" in st:
            raise ValueError(
                "Capsule.source_type must be null or a non-empty string of at most 128 characters"
            )


def _pick(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key in payload and payload[key] is not None:
            out[key] = payload[key]
    return out


def _prepare_gene(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    _validate_gene_payload(payload)

    result: dict[str, Any] = {
        "type": "Gene",
        "id": (
            payload["id"]
            if isinstance(payload.get("id"), str) and payload.get("id")
            else ctx["localId"]
        ),
        "category": payload.get("category") or "innovate",
        "signals_match": list(payload["signals_match"]),
        "strategy": list(payload["strategy"]) if isinstance(payload.get("strategy"), list) else [],
        "schema_version": (
            payload["schema_version"]
            if isinstance(payload.get("schema_version"), str)
            else SCHEMA_VERSION
        ),
        "summary": (
            payload["summary"]
            if isinstance(payload.get("summary"), str)
            else (ctx.get("summary") or "")
        ),
        "hub_asset_id": ctx["assetId"],
        "synced_at": ctx["syncedAt"],
    }

    for field in _GENE_ARRAY_FIELDS:
        if field in ("signals_match", "strategy"):
            continue
        if field in payload and payload[field] is not None:
            result[field] = (
                list(payload[field]) if isinstance(payload[field], list) else payload[field]
            )

    for field in _GENE_OPTIONAL_SCALAR:
        if field in payload and payload[field] is not None:
            result[field] = payload[field]

    for field in _GENE_OPTIONAL_OBJECT:
        if field in payload and payload[field] is not None:
            result[field] = payload[field]

    for field in _GENE_OPTIONAL_LIST_OF_OBJ:
        if field in payload and payload[field] is not None:
            result[field] = payload[field]

    # Never retain the legacy `signals` alias or inbound hub asset_id.
    result.pop("signals", None)
    result["asset_id"] = compute_asset_id(result)
    return result


def _prepare_capsule(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    _validate_capsule_payload(payload)

    result: dict[str, Any] = {
        "type": "Capsule",
        "id": (
            payload["id"]
            if isinstance(payload.get("id"), str) and payload.get("id")
            else ctx["localId"]
        ),
        "schema_version": (
            payload["schema_version"]
            if isinstance(payload.get("schema_version"), str)
            else SCHEMA_VERSION
        ),
        "trigger": (list(payload["trigger"]) if isinstance(payload.get("trigger"), list) else []),
        "execution_trace": (
            list(payload["execution_trace"])
            if isinstance(payload.get("execution_trace"), list)
            else []
        ),
        "outcome": dict(payload["outcome"]),
        "summary": (
            payload["summary"]
            if isinstance(payload.get("summary"), str)
            else (ctx.get("summary") or "")
        ),
        "hub_asset_id": ctx["assetId"],
        "synced_at": ctx["syncedAt"],
    }

    for field in _CAPSULE_COPY_FIELDS:
        if field in ("schema_version", "trigger", "execution_trace", "outcome", "summary"):
            continue
        if field in payload and payload[field] is not None:
            result[field] = payload[field]

    result["asset_id"] = compute_asset_id(result)
    return result


def prepare_sync_asset(opts: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a Hub asset payload into a locally installable Gene/Capsule.

    Required context keys: ``assetType``, ``assetId``, ``syncedAt``.
    ``localId`` / ``summary`` fill gaps when the payload omits id/summary.
    """
    options = opts or {}
    if not options.get("assetId") or not isinstance(options.get("assetId"), str):
        raise ValueError("assetId is required and must be a string")
    if not options.get("syncedAt") or not isinstance(options.get("syncedAt"), str):
        raise ValueError("syncedAt is required and must be a string")

    asset_type = options.get("assetType")
    payload = options.get("payload")
    if not _is_plain_object(payload):
        payload = {}
    # Defensive: only plain dicts — drop non-own contract junk by re-keying.
    clean_payload = {
        k: v
        for k, v in payload.items()
        if isinstance(k, str) and k not in ("constructor", "prototype", "__proto__")
    }

    ctx = {
        "assetId": options["assetId"],
        "localId": options.get("localId") or "",
        "summary": options.get("summary") or "",
        "syncedAt": options["syncedAt"],
    }

    if asset_type == "Gene":
        return _prepare_gene(clean_payload, ctx)
    if asset_type == "Capsule":
        return _prepare_capsule(clean_payload, ctx)
    raise ValueError(f"unsupported asset type: {asset_type}")


def install_sync_asset(
    asset: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Install a prepared sync asset; *force* overwrites local id collisions."""
    from evolver.gep.asset_store import (  # noqa: PLC0415
        append_capsule,
        load_capsules,
        load_genes,
        upsert_gene,
    )

    asset_type = asset.get("type")
    local_id = asset.get("id")
    if not local_id:
        return {"ok": False, "error": "missing_id"}

    if asset_type == "Gene":
        existing_list = load_genes()
        existing = next((g for g in existing_list if g.get("id") == local_id), None)
        if existing is not None and not force:
            return {
                "ok": False,
                "error": "local_id_conflict",
                "id": local_id,
                "existing_asset_id": existing.get("asset_id"),
            }
        upsert_gene(asset)
        return {
            "ok": True,
            "type": "Gene",
            "id": local_id,
            "asset_id": asset.get("asset_id") or compute_asset_id(asset),
            "forced": bool(force and existing is not None),
        }

    if asset_type == "Capsule":
        if not force:
            for cap in load_capsules():
                if cap.get("id") == local_id:
                    return {
                        "ok": False,
                        "error": "local_id_conflict",
                        "id": local_id,
                        "existing_asset_id": cap.get("asset_id"),
                    }
        append_capsule(asset)
        return {
            "ok": True,
            "type": "Capsule",
            "id": local_id,
            "asset_id": asset.get("asset_id") or compute_asset_id(asset),
            "forced": force,
        }

    return {"ok": False, "error": f"unknown_type:{asset_type}"}


__all__ = [
    "HUB_GENE_CATEGORIES",
    "install_sync_asset",
    "prepare_sync_asset",
]
