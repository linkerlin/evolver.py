"""CLI contracts for ``reuse.v1`` and ``publish.v1``.

Equivalent to evolver/src/gep/cliContracts.js.
"""

# Port of Node cliContracts.js — parser/command orchestrators are intentionally branchy.
# ruff: noqa: PLR0911, PLR0912, PLR0915, E501, SIM108, SIM101

from __future__ import annotations

import builtins
import contextlib
import copy
import inspect
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO, cast

from evolver.gep import a2a_protocol as a2a
from evolver.gep import asset_store
from evolver.gep.content_hash import compute_asset_id
from evolver.gep.paths import get_gep_assets_dir
from evolver.gep.sanitize import full_leak_check, redact_string

REUSE_CONTRACT = "reuse.v1"
PUBLISH_CONTRACT = "publish.v1"
REVERSIBILITY = "irreversible"
MAX_ASSETS = 50

ASSET_FLAGS = frozenset({"--asset", "--gene", "--capsule", "--event"})
ASSET_FLAG_LIST = ("--asset", "--gene", "--capsule", "--event")

NODE_SCOPED_ENDPOINT_PATHS = frozenset({"/a2a/fetch", "/a2a/validate", "/a2a/publish"})

REUSE_FAILURE_REASONS = frozenset(
    {
        "missing_id",
        "cli_unavailable",
        "auth_required",
        "not_found",
        "network_error",
        "unsupported",
        "internal_error",
    }
)

PUBLISH_FAILURE_REASONS = frozenset(
    {
        "redaction_unavailable",
        "leak_detected",
        "schema_invalid",
        "bundle_required",
        "quality_gate_failed",
        "auth_required",
        "insufficient_credits",
        "network_error",
        "unsupported",
        "cli_unavailable",
        "internal_error",
    }
)

HUB_METADATA_KEYS = frozenset(
    {
        "credit_cost",
        "gdi_score",
        "success_rate",
        "reuse_count",
        "ranking_score",
        "source_node_id",
        "fetched_at",
        "receipt",
        "hub_receipt",
        "already_purchased",
        "_semantic_similarity",
        "semantic_similarity",
        "_search_score",
        "search_score",
        "_match_score",
        "match_score",
        "_retrieval_rank",
        "retrieval_rank",
    }
)


class ContractError(Exception):
    def __init__(self, reason: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.reason = reason
        self.safe_message = safe_message


class _StdoutLike(Protocol):
    def write(self, data: str) -> int: ...


class _Deps(Protocol):
    out: TextIO | _StdoutLike
    hub_url: str | None
    node_secret: str | None
    assets_dir: str | Path | None
    no_asset_store_init: bool
    timeout_ms: int


def parse_reuse_args(args: list[str]) -> dict[str, Any]:
    asset_id: str | None = None
    json_out = False
    idx = 0
    while idx < len(args):
        token = args[idx]
        if not token:
            idx += 1
            continue
        if token == "--json":
            json_out = True
            idx += 1
            continue
        if token == "--id":
            nxt = args[idx + 1] if idx + 1 < len(args) else None
            if not nxt or nxt.startswith("--"):
                return {
                    "ok": False,
                    "reason": "missing_id",
                    "message": "reuse requires --id <asset_id>",
                }
            asset_id = nxt.strip()
            idx += 2
            continue
        if token.startswith("--id="):
            asset_id = token[len("--id=") :].strip()
            idx += 1
            continue
        if token.startswith("--"):
            return {"ok": False, "reason": "unsupported", "message": "unsupported reuse flag"}
        return {"ok": False, "reason": "unsupported", "message": "unsupported reuse argument"}
    if not json_out:
        return {"ok": False, "reason": "unsupported", "message": "reuse requires --json"}
    if not asset_id:
        return {"ok": False, "reason": "missing_id", "message": "reuse requires --id <asset_id>"}
    if len(asset_id) > 200:
        return {
            "ok": False,
            "reason": "missing_id",
            "message": "asset id must be <= 200 characters",
        }
    return {"ok": True, "assetId": asset_id, "jsonOut": True}


def parse_publish_args(args: list[str]) -> dict[str, Any]:
    asset_refs: list[str] = []
    dry_run = False
    json_out = False
    idx = 0
    while idx < len(args):
        token = args[idx]
        if not token:
            idx += 1
            continue
        if token == "--dry-run":
            dry_run = True
            idx += 1
            continue
        if token == "--json":
            json_out = True
            idx += 1
            continue
        equal_flag = next((flag for flag in ASSET_FLAG_LIST if token.startswith(flag + "=")), None)
        if equal_flag:
            value = token[len(equal_flag) + 1 :].strip()
            if not value:
                return {
                    "ok": False,
                    "reason": "bundle_required",
                    "message": f"{equal_flag} requires a value",
                }
            asset_refs.append(value)
            idx += 1
            continue
        if token in ASSET_FLAGS:
            nxt = args[idx + 1] if idx + 1 < len(args) else None
            if not nxt or nxt.startswith("--"):
                return {
                    "ok": False,
                    "reason": "bundle_required",
                    "message": f"{token} requires a value",
                }
            asset_refs.append(nxt.strip())
            idx += 2
            continue
        if not token.startswith("--"):
            return {"ok": False, "reason": "unsupported", "message": "unsupported publish argument"}
        return {"ok": False, "reason": "unsupported", "message": "unsupported publish flag"}
    if not json_out:
        return {"ok": False, "reason": "unsupported", "message": "publish requires --json"}
    refs = [ref for ref in asset_refs if ref]
    if not refs:
        return {
            "ok": False,
            "reason": "bundle_required",
            "message": "publish requires --asset <id|path>",
        }
    if len(refs) > MAX_ASSETS:
        return {
            "ok": False,
            "reason": "bundle_required",
            "message": f"publish supports at most {MAX_ASSETS} assets",
        }
    return {"ok": True, "assetRefs": refs, "dryRun": dry_run, "jsonOut": True}


def _record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _string_field(value: Any, key: str) -> str | None:
    obj = _record(value)
    if not obj:
        return None
    raw = obj.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _safe_token_field(value: str | None) -> str | None:
    if not value:
        return None

    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value) else None


def _number_field(value: Any, key: str) -> int | None:
    obj = _record(value)
    if not obj:
        return None
    raw = obj.get(key)
    if isinstance(raw, int):
        n = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            n = int(raw)
        except ValueError:
            return None
    else:
        return None
    return n if isinstance(n, int) else None


def _first_number_field(value: Any, keys: list[str]) -> int | None:
    for key in keys:
        n = _number_field(value, key)
        if n is not None:
            return n
    return None


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _canonical_asset_type(value: Any) -> str | None:
    if value in ("Gene", "gene"):
        return "Gene"
    if value in ("Capsule", "capsule"):
        return "Capsule"
    if value in ("EvolutionEvent", "event", "Evolutionevent"):
        return "EvolutionEvent"
    return None


def _looks_like_file(value: str) -> bool:
    try:
        path = Path(value)
        return path.is_file()
    except OSError:
        return False


def _normalize_asset(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("schema_invalid", "asset is not an object")
    asset_type = _canonical_asset_type(value.get("type"))
    if not asset_type:
        raise ContractError("schema_invalid", "asset type must be Gene, Capsule, or EvolutionEvent")
    out = dict(value)
    out["type"] = asset_type
    out.setdefault("asset_id", "IGNORED")
    return out


def _read_json_array(path: Path, key: str | None) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        parsed = json.loads(path.read_text(encoding="utf-8"))
        rows = parsed.get(key) if key else parsed
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("schema_invalid", "asset schema is invalid") from exc


def _read_json_lines(path: Path, asset_type: str | None) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if asset_type and row.get("type") != asset_type:
                continue
            out.append(row)
        return out
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("schema_invalid", "asset schema is invalid") from exc


def _load_local_assets_read_only(deps: dict[str, Any]) -> list[dict[str, Any]]:
    assets_dir = Path(deps.get("assets_dir") or get_gep_assets_dir())
    return (
        _read_json_array(assets_dir / "genes.json", "genes")
        + _read_json_lines(assets_dir / "genes.jsonl", "Gene")
        + _read_json_array(assets_dir / "capsules.json", "capsules")
        + _read_json_lines(assets_dir / "capsules.jsonl", "Capsule")
        + _read_json_lines(assets_dir / "events.jsonl", "EvolutionEvent")
    )


def _load_local_assets_from_store(deps: dict[str, Any]) -> list[dict[str, Any]]:
    store = deps.get("asset_store") or asset_store
    load_genes = getattr(store, "load_genes", None)
    load_capsules = getattr(store, "load_capsules", None)
    read_events = getattr(store, "read_all_events", None)
    genes = load_genes() if callable(load_genes) else []
    capsules = load_capsules() if callable(load_capsules) else []
    events = read_events() if callable(read_events) else []
    return list(genes) + list(capsules) + list(events)


def _needs_local_asset_lookup(refs: list[str]) -> bool:
    return any(not _looks_like_file(ref) for ref in refs)


def _load_asset_ref_from_lookup(ref: str, all_assets: list[dict[str, Any]]) -> dict[str, Any]:
    if _looks_like_file(ref):
        return _normalize_asset(json.loads(Path(ref).read_text(encoding="utf-8")))
    found = next(
        (asset for asset in all_assets if asset.get("asset_id") == ref or asset.get("id") == ref),
        None,
    )
    if not found:
        raise ContractError("schema_invalid", f"asset not found: {ref}")
    return _normalize_asset(found)


def _load_asset_refs(refs: list[str], deps: dict[str, Any]) -> list[dict[str, Any]]:
    if _needs_local_asset_lookup(refs):
        if deps.get("no_asset_store_init") and not deps.get("asset_store"):
            all_assets = _load_local_assets_read_only(deps)
        else:
            all_assets = _load_local_assets_from_store(deps)
    else:
        all_assets = []
    return [_load_asset_ref_from_lookup(ref, all_assets) for ref in refs]


def _check_bundle(bundle: list[dict[str, Any]]) -> dict[str, Any]:
    genes = [asset for asset in bundle if asset.get("type") == "Gene"]
    capsules = [asset for asset in bundle if asset.get("type") == "Capsule"]
    events = [asset for asset in bundle if asset.get("type") == "EvolutionEvent"]
    if len(genes) > 1 or len(capsules) > 1 or len(events) > 1:
        return {
            "ok": False,
            "message": "publish supports one Gene + one Capsule + optional one EvolutionEvent bundle",
        }
    if not genes or not capsules:
        return {"ok": False, "message": "publish requires Gene + Capsule bundle"}
    for gene in genes:
        ids = {gene.get("asset_id"), gene.get("id")} - {None}
        if not any(capsule.get("gene") in ids for capsule in capsules):
            return {"ok": False, "message": "gene must publish with its capsule"}
    return {"ok": True}


def _known_local_secrets(deps: dict[str, Any]) -> list[str]:
    secrets: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and len(value) >= 8:
            secrets.add(value)

    if deps.get("node_secret") is not None:
        add(deps.get("node_secret"))
    else:
        add(a2a.get_hub_node_secret())
    for key, value in os.environ.items():
        if any(
            token in key.upper()
            for token in ("SECRET", "TOKEN", "API_KEY", "PASSWORD", "AUTH", "CREDENTIAL")
        ):
            add(value)
    return sorted(secrets, key=len, reverse=True)


def _redact_known_secrets_in_string(
    value: str, deps: dict[str, Any], known: list[str] | None = None
) -> str:
    result = redact_string(value)
    for secret in known or _known_local_secrets(deps):
        result = result.replace(secret, "[REDACTED]")
    return result


def _unique_object_key(target: dict[str, Any], key: str) -> str:
    if key not in target:
        return key
    idx = 2
    while f"{key}_{idx}" in target:
        idx += 1
    return f"{key}_{idx}"


def _sanitize_object_key(key: str, deps: dict[str, Any], secrets: list[str]) -> str:
    clean = _redact_known_secrets_in_string(redact_string(str(key)), deps, secrets)
    return clean or "[REDACTED]"


def _redact_known_secrets(value: Any, deps: dict[str, Any], known: list[str] | None = None) -> Any:
    secrets_list = known or _known_local_secrets(deps)
    if isinstance(value, str):
        return _redact_known_secrets_in_string(value, deps, secrets_list)
    if not isinstance(value, dict):
        if isinstance(value, list):
            return [_redact_known_secrets(item, deps, secrets_list) for item in value]
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        clean_key = _unique_object_key(out, _sanitize_object_key(str(key), deps, secrets_list))
        out[clean_key] = _redact_known_secrets(item, deps, secrets_list)
    return out


def _sanitize_for_contract(value: Any, deps: dict[str, Any]) -> Any:
    if isinstance(value, dict) or isinstance(value, list):
        base = copy.deepcopy(value)
    else:
        base = value
    return _redact_known_secrets(base, deps)


def _sanitize_text(value: str, deps: dict[str, Any]) -> str:
    return _redact_known_secrets_in_string(redact_string(value), deps)


def _leak_check(bundle: Any) -> dict[str, Any]:
    result = full_leak_check(bundle if isinstance(bundle, str) else json.dumps(bundle))
    hard: list[dict[str, Any]] = []
    for leak in result.get("pattern_leaks", []):
        if isinstance(leak, dict) and leak.get("type") != "local_path":
            hard.append(leak)
    for leak in result.get("env_leaks", []):
        if isinstance(leak, dict):
            hard.append(leak)
    return {"blocked": len(hard) > 0}


def build_publish_bundle(refs: list[str], deps: dict[str, Any]) -> dict[str, Any]:
    try:
        original = _load_asset_refs(refs, deps)
    except ContractError:
        return {
            "ok": False,
            "reason": "schema_invalid",
            "message": "asset schema is invalid",
            "gates": {"schema": "fail"},
        }
    bundle_check = _check_bundle(original)
    if not bundle_check.get("ok"):
        return {
            "ok": False,
            "reason": "bundle_required",
            "message": bundle_check.get("message", "publish requires a complete asset bundle"),
            "gates": {"schema": "pass", "bundle": "fail"},
        }
    try:
        sanitized = []
        for asset in original:
            clean = _sanitize_for_contract(asset, deps)
            if not isinstance(clean, dict):
                raise ContractError("redaction_unavailable", "redaction unavailable")
            clean["asset_id"] = compute_asset_id(clean)
            sanitized.append(clean)
    except ContractError:
        return {
            "ok": False,
            "reason": "redaction_unavailable",
            "message": "redaction unavailable",
            "gates": {"redaction": "unavailable"},
        }
    leak = _leak_check(sanitized)
    block_reasons = ["leak_detected"] if leak["blocked"] else []
    gates = {
        "redaction": "pass",
        "leak": "fail" if leak["blocked"] else "pass",
        "schema": "pass",
        "bundle": "pass",
        "quality": "pass",
    }
    return {
        "ok": True,
        "original": original,
        "sanitized": sanitized,
        "blockReasons": block_reasons,
        "gates": gates,
        "assets": _summarize_publish_assets(sanitized),
    }


def _summarize_publish_assets(assets: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        row: dict[str, str] = {}
        asset_id = _string_field(asset, "asset_id")
        asset_type = _canonical_asset_type(asset.get("type"))
        if asset_id:
            row["asset_id"] = asset_id
        if asset_type:
            row["type"] = asset_type
        if row:
            out.append(row)
    return out


def _publish_payload_assets(message: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _record(message.get("payload")) or {}
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return []
    return [asset for asset in assets if isinstance(asset, dict)]


def _sanitize_publish_assets(
    assets: list[dict[str, Any]], deps: dict[str, Any]
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        clean = cast(dict[str, Any], _sanitize_for_contract(asset, deps))
        clean["asset_id"] = compute_asset_id(clean)
        cleaned.append(clean)
    return cleaned


def _get_a2a(deps: dict[str, Any]) -> Any:
    return deps.get("a2a") or a2a


def _is_publish_signing_auth_error(error: Exception) -> bool:
    msg = str(error)
    return bool(
        re.search(
            r"node_secret|signing|authentication required|Hub URL is required",
            msg,
            re.IGNORECASE,
        )
    )


def _build_unsigned_publish_preview_message(
    *,
    gene: dict[str, Any],
    capsule: dict[str, Any],
    event: dict[str, Any] | None,
    node_id: str,
) -> dict[str, Any]:
    assets = [gene, capsule] + ([event] if event else [])
    stamped = []
    for asset in assets:
        copy_asset = copy.deepcopy(asset)
        copy_asset["asset_id"] = compute_asset_id(copy_asset)
        stamped.append(copy_asset)
    return {
        "protocol": a2a.PROTOCOL_NAME,
        "protocol_version": a2a.PROTOCOL_VERSION,
        "message_type": "publish",
        "message_id": a2a._new_message_id(),
        "sender_id": node_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {"assets": stamped},
    }


def _build_publish_message_from_assets(
    assets: list[dict[str, Any]],
    deps: dict[str, Any],
    *,
    preview: bool,
) -> dict[str, Any]:
    a2a_mod = _get_a2a(deps)
    gene = next((asset for asset in assets if asset.get("type") == "Gene"), None)
    capsule = next((asset for asset in assets if asset.get("type") == "Capsule"), None)
    event = next((asset for asset in assets if asset.get("type") == "EvolutionEvent"), None)
    if not gene or not capsule:
        raise ContractError("bundle_required", "publish requires Gene + Capsule bundle")
    preview_node = deps.get("node_id") or a2a.non_persisted_node_id() or a2a.DRY_RUN_NODE_ID
    if preview:
        try:
            return cast(
                dict[str, Any],
                a2a_mod.build_publish_bundle(
                    gene=gene,
                    capsule=capsule,
                    event=event,
                    node_id=preview_node,
                ),
            )
        except Exception as exc:
            if not _is_publish_signing_auth_error(exc):
                raise
            if not _has_hub_authorization(deps):
                raise ContractError("auth_required", "Hub authentication required") from exc
            return _build_unsigned_publish_preview_message(
                gene=gene,
                capsule=capsule,
                event=event,
                node_id=preview_node,
            )
    if not _get_hub_url(deps):
        raise ContractError("auth_required", "Hub URL is required")
    if not _has_hub_authorization(deps):
        raise ContractError("auth_required", "Hub authentication required")
    try:
        return cast(
            dict[str, Any],
            a2a_mod.build_publish_bundle(gene=gene, capsule=capsule, event=event),
        )
    except Exception as exc:
        if not _is_publish_signing_auth_error(exc):
            raise
        return _build_unsigned_publish_preview_message(
            gene=gene,
            capsule=capsule,
            event=event,
            node_id=preview_node,
        )


def _finalize_publish_message(
    message: dict[str, Any], deps: dict[str, Any], *, preview: bool
) -> dict[str, Any]:
    signed_assets = _publish_payload_assets(message)
    final_assets = _sanitize_publish_assets(signed_assets, deps)
    if _same_json(final_assets, signed_assets):
        return message
    resigned = _build_publish_message_from_assets(final_assets, deps, preview=preview)
    resigned_assets = _publish_payload_assets(resigned)
    final_resigned = _sanitize_publish_assets(resigned_assets, deps)
    if not _same_json(final_resigned, resigned_assets):
        raise ContractError("redaction_unavailable", "redaction unavailable")
    return resigned


def _build_publish_message(
    sanitized: list[dict[str, Any]],
    deps: dict[str, Any],
    *,
    preview: bool,
) -> dict[str, Any]:
    initial_assets = _sanitize_publish_assets(sanitized, deps)
    message = _build_publish_message_from_assets(initial_assets, deps, preview=preview)
    return _finalize_publish_message(message, deps, preview=preview)


def _sync_bundle_from_publish_message(bundle: dict[str, Any], message: dict[str, Any]) -> None:
    final_assets = _publish_payload_assets(message)
    if not final_assets:
        raise ContractError("bundle_required", "publish requires a complete asset bundle")
    bundle["sanitized"] = final_assets
    bundle["assets"] = _summarize_publish_assets(final_assets)
    leak = _leak_check(final_assets)
    block_reasons = list(bundle.get("blockReasons") or [])
    if leak["blocked"] and "leak_detected" not in block_reasons:
        block_reasons.append("leak_detected")
    bundle["blockReasons"] = block_reasons
    gates = dict(bundle.get("gates") or {})
    gates["leak"] = "fail" if leak["blocked"] else "pass"
    bundle["gates"] = gates


def _strip_hub_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in asset.items() if key not in HUB_METADATA_KEYS}


def _verify_reuse_asset_id(asset: dict[str, Any], requested_id: str) -> bool:
    if asset.get("asset_id") != requested_id:
        return False
    return compute_asset_id(asset) == requested_id


def _is_reuse_asset_store_stable(asset: dict[str, Any]) -> bool:
    return bool(asset.get("schema_version"))


def _find_local_asset_by_type_and_id(
    store: Any, asset_type: str, local_id: str
) -> dict[str, Any] | None:
    loader = store.load_genes if asset_type == "Gene" else store.load_capsules
    assets = loader() if callable(loader) else []
    return next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict)
            and asset.get("type") == asset_type
            and str(asset.get("id")) == str(local_id)
        ),
        None,
    )


def _assert_no_local_reuse_id_conflict(asset: dict[str, Any], store: Any, asset_type: str) -> None:
    local_id = asset.get("id")
    if not local_id:
        return
    local = _find_local_asset_by_type_and_id(store, asset_type, str(local_id))
    if not local:
        return
    incoming_id = asset.get("asset_id") or compute_asset_id(asset)
    local_id_hash = local.get("asset_id") or compute_asset_id(local)
    if incoming_id != local_id_hash:
        raise ContractError("internal_error", "local asset id conflict")


def _prepare_reuse_asset_store(asset: dict[str, Any], deps: dict[str, Any]) -> Any:
    store = deps.get("asset_store") or asset_store
    asset_type = asset.get("type")
    if asset_type == "Gene" and callable(getattr(store, "upsert_gene", None)):
        _assert_no_local_reuse_id_conflict(asset, store, "Gene")
        return store
    if asset_type == "Capsule" and callable(getattr(store, "upsert_capsule", None)):
        _assert_no_local_reuse_id_conflict(asset, store, "Capsule")
        return store
    if asset_type == "EvolutionEvent" and callable(getattr(store, "append_event_jsonl", None)):
        return store
    raise ContractError("unsupported", "unsupported asset type")


def _store_reused_asset(
    asset: dict[str, Any], deps: dict[str, Any], prepared_store: Any | None = None
) -> str:
    store = prepared_store or _prepare_reuse_asset_store(asset, deps)
    asset_type = asset.get("type")
    if asset_type == "Gene":
        _assert_no_local_reuse_id_conflict(asset, store, "Gene")
        store.upsert_gene(asset)
    elif asset_type == "Capsule":
        _assert_no_local_reuse_id_conflict(asset, store, "Capsule")
        store.upsert_capsule(asset)
    elif asset_type == "EvolutionEvent":
        store.append_event_jsonl(asset)
    else:
        raise ContractError("unsupported", "unsupported asset type")
    return str(asset.get("asset_id") or compute_asset_id(asset))


def _prepare_hub_provenance(deps: dict[str, Any]) -> dict[str, Any]:
    target_dir = Path(deps.get("assets_dir") or get_gep_assets_dir())
    file_path = target_dir / "provenance.jsonl"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not file_path.is_file():
            raise OSError("not a file")
        stat = file_path.stat() if file_path.exists() else None
        return {
            "file": file_path,
            "existed": stat is not None,
            "size": stat.st_size if stat else 0,
        }
    except OSError as exc:
        raise ContractError("internal_error", "provenance write failed") from exc


def _mark_hub_provenance(
    asset_id: str, deps: dict[str, Any], prepared: dict[str, Any] | None = None
) -> None:
    if not asset_id:
        raise ContractError("internal_error", "provenance write failed")
    target = prepared or _prepare_hub_provenance(deps)
    line = (
        json.dumps(
            {
                "assetId": asset_id,
                "source": "hub",
                "trusted": False,
                "at": datetime.now(UTC).isoformat(),
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    file_path = cast(Path, target["file"])
    try:
        with file_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
        target["entry"] = line
    except OSError as exc:
        raise ContractError("internal_error", "provenance write failed") from exc


def _rollback_hub_provenance(prepared: dict[str, Any] | None) -> None:
    if not prepared or "file" not in prepared:
        return
    file_path = cast(Path, prepared["file"])
    try:
        if not file_path.exists():
            return
        previous_size = int(prepared.get("size", 0))
        with file_path.open("r+b") as handle:
            handle.truncate(previous_size)
        if not prepared.get("existed") and previous_size == 0:
            with contextlib.suppress(OSError):
                file_path.unlink(missing_ok=True)
    except OSError:
        return


def _get_hub_url(deps: dict[str, Any]) -> str | None:
    if deps.get("hub_url"):
        return str(deps["hub_url"])
    a2a_mod = _get_a2a(deps)
    getter = getattr(a2a_mod, "get_hub_url", None)
    if callable(getter):
        return cast(str | None, getter())
    return os.environ.get("A2A_HUB_URL")


def _get_hub_node_secret(deps: dict[str, Any]) -> str | None:
    if "node_secret" in deps:
        secret = deps.get("node_secret")
        return str(secret) if secret else None
    a2a_mod = _get_a2a(deps)
    getter = getattr(a2a_mod, "get_hub_node_secret", None)
    if callable(getter):
        return cast(str | None, getter())
    return os.environ.get("A2A_NODE_SECRET")


def _has_authorization_header(headers: dict[str, str]) -> bool:
    value = headers.get("Authorization") or headers.get("authorization")
    return (
        isinstance(value, str)
        and value.lower().startswith("bearer ")
        and len(value.split(maxsplit=1)) == 2
    )


def _build_hub_headers_safe(a2a_mod: Any) -> dict[str, str]:
    try:
        builder = getattr(a2a_mod, "build_hub_headers", None)
        return builder() if callable(builder) else {}
    except Exception:
        return {}


def _get_hub_node_secret_version_safe(a2a_mod: Any) -> str | None:
    try:
        getter = getattr(a2a_mod, "get_hub_node_secret_version", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _build_node_scoped_hub_headers_safe(a2a_mod: Any, deps: dict[str, Any]) -> dict[str, str]:
    if "node_secret" not in deps:
        builder = getattr(a2a_mod, "build_node_scoped_hub_headers", None)
        if callable(builder):
            try:
                headers = builder() or {}
                if _has_authorization_header(headers):
                    return headers
            except Exception:
                pass
    secret = _get_hub_node_secret(deps)
    if not secret:
        return {}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
    version = _get_hub_node_secret_version_safe(a2a_mod)
    if version:
        headers["X-EvoMap-Node-Secret-Version"] = version
    return headers


def _build_envelope_headers(
    endpoint_path: str, deps: dict[str, Any], a2a_mod: Any
) -> dict[str, str]:
    if endpoint_path in NODE_SCOPED_ENDPOINT_PATHS:
        return _build_node_scoped_hub_headers_safe(a2a_mod, deps)
    return _build_hub_headers_safe(a2a_mod)


def _has_hub_authorization(deps: dict[str, Any]) -> bool:
    # All cliContracts endpoints are node-scoped. OAuth-only authorization
    # must never be forwarded to fetch/validate/publish.
    return bool(_get_hub_node_secret(deps))


async def _safe_json_response(response: Any) -> Any:
    if isinstance(response, dict):
        text_fn = response.get("text")
        json_fn = response.get("json")
        if "body" in response and json_fn is None and text_fn is None:
            return response.get("body")
    else:
        text_fn = getattr(response, "text", None)
        json_fn = getattr(response, "json", None)

    if callable(text_fn):
        try:
            text = await text_fn() if inspect.iscoroutinefunction(text_fn) else text_fn()
            if inspect.isawaitable(text):
                text = await text
            try:
                return json.loads(text)
            except (TypeError, json.JSONDecodeError):
                return {"error": str(text)[:200]} if text else {}
        except Exception:
            pass
    if callable(json_fn):
        try:
            value = await json_fn() if inspect.iscoroutinefunction(json_fn) else json_fn()
            if inspect.isawaitable(value):
                value = await value
            return value
        except Exception:
            pass
    if isinstance(response, dict) and "body" in response:
        return response["body"]
    return {}


async def _post_envelope(
    endpoint_path: str, message: dict[str, Any], deps: dict[str, Any]
) -> dict[str, Any]:
    hub_url = _get_hub_url(deps)
    if not hub_url:
        raise ContractError("auth_required", "Hub URL is required")
    a2a_mod = _get_a2a(deps)
    headers = _build_envelope_headers(endpoint_path, deps, a2a_mod)
    if not _has_authorization_header(headers):
        raise ContractError("auth_required", "Hub authentication required")
    fetch_impl = deps.get("hub_fetch")
    timeout_ms = int(deps.get("timeout_ms") or 30000)
    endpoint = hub_url.rstrip("/") + endpoint_path
    if fetch_impl is not None:
        try:
            opts = {
                "method": "POST",
                "headers": headers,
                "body": json.dumps(message),
                "timeout_ms": timeout_ms,
            }
            try:
                result = fetch_impl(endpoint, opts)
            except TypeError:
                result = fetch_impl(
                    endpoint,
                    method="POST",
                    headers=headers,
                    body=opts["body"],
                    timeout_ms=timeout_ms,
                )
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict) and "body" in result and "json" not in result:
                return {
                    "ok": bool(result.get("ok")),
                    "status": int(result.get("status") or 0),
                    "body": result.get("body"),
                }
            body = await _safe_json_response(result)
            if isinstance(result, dict):
                status = result.get("status", 0)
                ok = result.get("ok")
            else:
                status = getattr(result, "status", 0)
                ok = getattr(result, "ok", None)
            if ok is None:
                ok = isinstance(status, int) and 200 <= status < 300
            return {"ok": bool(ok), "status": int(status or 0), "body": body}
        except ContractError:
            raise
        except Exception:
            return {"ok": False, "status": 0, "body": {"error": "network_error"}}
    return a2a.post_hub_envelope(
        endpoint_path, message, hub_url=hub_url, headers=headers, timeout_ms=timeout_ms
    )


def _assets_from_body(body: Any) -> list[dict[str, Any]]:
    root = _record(body) or {}
    payload = _record(root.get("payload")) or {}
    rows_list: Any = (
        payload.get("results")
        if isinstance(payload.get("results"), list)
        else payload.get("assets")
        if isinstance(payload.get("assets"), list)
        else root.get("results")
        if isinstance(root.get("results"), list)
        else root.get("assets")
        if isinstance(root.get("assets"), list)
        else []
    )
    rows = cast(list[Any], rows_list)
    return [row for row in rows if isinstance(row, dict)]


async def _fetch_asset_by_id(asset_id: str, deps: dict[str, Any]) -> dict[str, Any] | None:
    fetcher = deps.get("fetch_asset_by_id")
    if callable(fetcher):
        result = fetcher(asset_id)
        if hasattr(result, "__await__"):
            result = await result
        return cast(dict[str, Any] | None, result)
    hub_url = _get_hub_url(deps)
    if not hub_url:
        raise ContractError("auth_required", "Hub URL is required")
    if not _has_hub_authorization(deps):
        raise ContractError("auth_required", "Hub authentication required")
    a2a_mod = _get_a2a(deps)
    builder = getattr(a2a_mod, "build_fetch", None)
    if not callable(builder):
        raise ContractError("internal_error", "evolver reuse failed")
    message = builder(asset_ids=[asset_id])
    posted = await _post_envelope("/a2a/fetch", message, deps)
    if not posted.get("ok"):
        stable = _stable_hub_reason(posted.get("body"), REUSE_FAILURE_REASONS)
        if stable in {"unsupported", "cli_unavailable"}:
            raise ContractError(stable, _reuse_reason_message(stable))
        if posted.get("status") in (401, 403):
            raise ContractError("auth_required", "Hub authentication required")
        if posted.get("status") == 404:
            return None
        raise ContractError("network_error", "Hub fetch failed")
    assets = _assets_from_body(posted.get("body"))
    return next((asset for asset in assets if asset.get("asset_id") == asset_id), None)


def _hub_reason(body: Any) -> str | None:
    root = _record(body) or {}
    payload = _record(root.get("payload")) or root
    return _string_field(payload, "reason") or _string_field(payload, "error")


def _stable_reason(reason: Any, allowed: frozenset[str]) -> str | None:
    safe = _safe_token_field(str(reason) if reason is not None else None)
    return safe if safe in allowed else None


def _stable_hub_reason(body: Any, allowed: frozenset[str]) -> str | None:
    return _stable_reason(_hub_reason(body), allowed)


def _normalize_validate_result(result: dict[str, Any]) -> dict[str, Any]:
    raw = _record(result) or {}
    status = (
        raw.get("status") if isinstance(raw.get("status"), int) else (200 if raw.get("ok") else 0)
    )
    body = raw.get("body")
    if not raw.get("ok"):
        return {
            "ok": False,
            "status": status,
            "reason": _stable_reason(raw.get("reason"), PUBLISH_FAILURE_REASONS)
            or _hub_reason(body)
            or f"hub {status}",
            "body": body,
        }
    payload = _record(body.get("payload") if isinstance(body, dict) else None)
    passed = bool(payload and (payload.get("valid") is True or payload.get("ok") is True))
    return {
        "ok": passed,
        "status": status,
        "reason": _string_field(payload, "reason") or _string_field(payload, "error"),
        "body": body,
    }


async def _post_validate(message: dict[str, Any], deps: dict[str, Any]) -> dict[str, Any]:
    validator = deps.get("validate")
    if callable(validator):
        result = validator(message)
        if hasattr(result, "__await__"):
            result = await result
        return _normalize_validate_result(cast(dict[str, Any], result))
    validate_message = dict(message)
    validate_message["message_type"] = "validate"
    result = await _post_envelope("/a2a/validate", validate_message, deps)
    return _normalize_validate_result(result)


async def _post_publish(message: dict[str, Any], deps: dict[str, Any]) -> dict[str, Any]:
    publisher = deps.get("publish")
    if callable(publisher):
        result = publisher(message)
        if hasattr(result, "__await__"):
            result = await result
        result = cast(dict[str, Any], result)
        if not result.get("ok"):
            return {
                "ok": False,
                "status": result.get("status", 0),
                "reason": _hub_reason(result.get("body")) or f"hub {result.get('status', 0)}",
                "body": result.get("body"),
            }
        return result
    result = await _post_envelope("/a2a/publish", message, deps)
    if not result.get("ok"):
        return {
            "ok": False,
            "status": result.get("status", 0),
            "reason": _hub_reason(result.get("body")) or f"hub {result.get('status', 0)}",
            "body": result.get("body"),
        }
    return result


def _credits_from_payload(payload: Any) -> dict[str, int | str] | None:
    root = _record(payload) or {}
    out: dict[str, int | str] = {}
    required = _number_field(root, "required")
    available = _number_field(root, "available")
    estimated = _first_number_field(root, ["estimated", "estimate"])
    charged = _number_field(root, "charged")
    balance_kind = _safe_token_field(
        _string_field(root, "balance_kind") or _string_field(root, "balanceKind")
    )
    if required is not None:
        out["required"] = required
    if available is not None:
        out["available"] = available
    if estimated is not None:
        out["estimated"] = estimated
    if charged is not None:
        out["charged"] = charged
    if balance_kind:
        out["balance_kind"] = balance_kind
    return out or None


def _extract_credits(body: Any) -> dict[str, int | str] | None:
    root = _record(body) or {}
    payload = _record(root.get("payload")) or root
    credits = _record(payload.get("credits")) or _record(payload.get("credit_cost")) or payload
    return _credits_from_payload(credits)


def _normalize_publish_status(body: Any) -> str | None:
    root = _record(body) or {}
    payload = _record(root.get("payload")) or root
    status = _string_field(payload, "status")
    if status:
        return status if status in {"queued", "accepted", "published"} else None
    decision = _string_field(payload, "decision")
    if not decision:
        return None
    if decision == "accept":
        return "accepted"
    if (
        decision in {"reject", "rejected"}
        and _string_field(payload, "reason") == "already_published"
    ):
        return "published"
    return None


def _publish_decision(body: Any) -> str | None:
    root = _record(body) or {}
    payload = _record(root.get("payload")) or root
    return _string_field(payload, "decision")


def _publish_reason_from_status(status: int) -> str:
    if status in (401, 403):
        return "auth_required"
    if status == 402:
        return "insufficient_credits"
    if status in (429, 0) or status >= 500:
        return "network_error"
    return "quality_gate_failed"


def _publish_reason_from_response(status: int, body: Any, reason: Any) -> str:
    return (
        _stable_reason(reason, PUBLISH_FAILURE_REASONS)
        or _stable_hub_reason(body, PUBLISH_FAILURE_REASONS)
        or _publish_reason_from_status(status)
    )


def _publish_retryable(reason: str) -> bool:
    return reason == "network_error"


def _publish_reason_message(reason: str) -> str:
    messages = {
        "redaction_unavailable": "redaction unavailable",
        "leak_detected": "leak detected after redaction",
        "schema_invalid": "asset schema is invalid",
        "bundle_required": "publish requires a complete asset bundle",
        "quality_gate_failed": "Hub quality gate failed",
        "auth_required": "Hub authentication required",
        "insufficient_credits": "insufficient credits",
        "network_error": "Hub unreachable",
        "unsupported": "publish unsupported",
        "cli_unavailable": "evolver CLI unavailable",
        "internal_error": "evolver publish failed",
    }
    return messages.get(reason, messages["internal_error"])


def _reuse_reason_message(reason: str) -> str:
    messages = {
        "missing_id": "reuse requires --id <asset_id>",
        "cli_unavailable": "evolver CLI unavailable",
        "auth_required": "Hub authentication required",
        "not_found": "asset not found",
        "network_error": "Hub fetch failed",
        "unsupported": "reuse unsupported",
        "internal_error": "evolver reuse failed",
    }
    return messages.get(reason, messages["internal_error"])


def _reuse_failure(reason: str, message: str) -> dict[str, Any]:
    return {"ok": False, "contract": REUSE_CONTRACT, "reason": reason, "message": message}


def _publish_failure(reason: str, message: str, **opts: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "contract": PUBLISH_CONTRACT,
        "reason": reason,
        "retryable": bool(opts.get("retryable")),
        "message": message,
    }
    for key in ("mode", "status", "gates", "assets", "credits"):
        if key in opts and opts[key] is not None:
            out[key] = opts[key]
    return out


def _dry_run_envelope(
    bundle: dict[str, Any], credits: dict[str, int | str] | None = None
) -> dict[str, Any]:
    block_reasons = list(bundle.get("blockReasons") or [])
    envelope: dict[str, Any] = {
        "ok": True,
        "contract": PUBLISH_CONTRACT,
        "mode": "dry_run",
        "reversibility": REVERSIBILITY,
        "blocked": len(block_reasons) > 0,
        "block_reasons": block_reasons,
        "assets": bundle.get("assets"),
        "gates": bundle.get("gates"),
    }
    if credits:
        envelope["credits"] = credits
    if "leak_detected" not in block_reasons:
        envelope["payload"] = {"assets": bundle.get("sanitized")}
    return envelope


def _write_json(
    out: TextIO | _StdoutLike,
    value: dict[str, Any],
    code: int,
    deps: dict[str, Any],
    machine_json: bool,
) -> int:
    line = json.dumps(_sanitize_for_contract(value, deps)) + "\n"
    if machine_json and out is sys.stdout and "_machine_json_stdout_write" in deps:
        deps["_machine_json_stdout_write"](line)
    else:
        out.write(line)
    return code


@contextlib.contextmanager
def _machine_json_console(deps: dict[str, Any]) -> Iterator[None]:
    original_stdout_write = sys.stdout.write
    original_stderr_write = sys.stderr.write
    original_print = builtins.print

    def redirect_stdout(chunk: str) -> int:
        return original_stderr_write(_sanitize_text(str(chunk), deps))

    def redirect_stderr(chunk: str) -> int:
        return original_stderr_write(_sanitize_text(str(chunk), deps))

    def patched_print(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("file") is sys.stdout:
            kwargs = dict(kwargs)
            kwargs["file"] = sys.stderr
        original_print(*args, **kwargs)

    deps["_machine_json_stdout_write"] = original_stdout_write
    sys.stdout.write = redirect_stdout  # type: ignore[method-assign]
    sys.stderr.write = redirect_stderr  # type: ignore[method-assign]
    builtins.print = patched_print
    try:
        yield
    finally:
        sys.stdout.write = original_stdout_write  # type: ignore[method-assign]
        sys.stderr.write = original_stderr_write  # type: ignore[method-assign]
        builtins.print = original_print
        deps.pop("_machine_json_stdout_write", None)


def _classify_error(error: Exception, command: str) -> dict[str, Any]:
    if isinstance(error, ContractError):
        return {
            "reason": error.reason,
            "message": error.safe_message,
            "retryable": error.reason == "network_error",
        }
    msg = str(error)

    if re.search(r"node_secret|credential|auth|401|403", msg, re.IGNORECASE):
        return {
            "reason": "auth_required",
            "message": "Hub authentication required",
            "retryable": False,
        }
    if re.search(r"A2A_HUB_URL|Hub URL", msg, re.IGNORECASE):
        return {"reason": "auth_required", "message": "Hub URL is required", "retryable": False}
    return {"reason": "internal_error", "message": f"evolver {command} failed", "retryable": False}


def _write_blocked_publish_result(
    bundle: dict[str, Any],
    parsed: dict[str, Any],
    write: Callable[[dict[str, Any], int], int],
) -> int | None:
    block_reasons = bundle.get("blockReasons") or []
    if not block_reasons:
        return None
    if parsed.get("dryRun"):
        return write(_dry_run_envelope(bundle), 0)
    reason = block_reasons[0] or "internal_error"
    return write(
        _publish_failure(
            reason,
            _publish_reason_message(reason),
            retryable=False,
            mode="publish",
            gates=bundle.get("gates"),
            assets=bundle.get("assets"),
        ),
        1,
    )


async def run_reuse_command(args: list[str], deps: dict[str, Any] | None = None) -> int:
    deps = dict(deps or {})
    out = deps.get("out") or sys.stdout
    parsed = parse_reuse_args(args)
    machine_json = bool(parsed.get("jsonOut") or out is sys.stdout)

    def write(value: dict[str, Any], code: int) -> int:
        return _write_json(out, value, code, deps, machine_json)

    if not parsed.get("ok"):
        return write(_reuse_failure(parsed["reason"], parsed["message"]), 1)

    with _machine_json_console(deps) if machine_json else contextlib.nullcontext():
        try:
            asset = await _fetch_asset_by_id(parsed["assetId"], deps)
            if not asset:
                return write(_reuse_failure("not_found", "asset not found"), 1)
            cleaned = _strip_hub_metadata(asset)
            if not _verify_reuse_asset_id(cleaned, parsed["assetId"]):
                return write(
                    _reuse_failure("internal_error", "asset integrity verification failed"),
                    1,
                )
            if not _is_reuse_asset_store_stable(cleaned):
                return write(
                    _reuse_failure("internal_error", "asset integrity verification failed"),
                    1,
                )
            store = _prepare_reuse_asset_store(cleaned, deps)
            provenance = _prepare_hub_provenance(deps)
            _mark_hub_provenance(parsed["assetId"], deps, provenance)
            try:
                stored_id = _store_reused_asset(cleaned, deps, store)
                if stored_id != parsed["assetId"]:
                    raise ContractError("internal_error", "asset integrity verification failed")
            except Exception:
                _rollback_hub_provenance(provenance)
                raise
            return write(
                {
                    "ok": True,
                    "contract": REUSE_CONTRACT,
                    "status": "ok",
                    "asset_id": stored_id,
                    "action": "reused",
                },
                0,
            )
        except Exception as exc:
            failure = _classify_error(exc, "reuse")
            return write(_reuse_failure(failure["reason"], failure["message"]), 1)


async def run_publish_command(args: list[str], deps: dict[str, Any] | None = None) -> int:
    deps = dict(deps or {})
    out = deps.get("out") or sys.stdout
    parsed = parse_publish_args(args)
    machine_json = bool(parsed.get("jsonOut") or out is sys.stdout)

    def write(value: dict[str, Any], code: int) -> int:
        return _write_json(out, value, code, deps, machine_json)

    if not parsed.get("ok"):
        return write(
            _publish_failure(parsed["reason"], parsed["message"], retryable=False),
            1,
        )

    with _machine_json_console(deps) if machine_json else contextlib.nullcontext():
        try:
            bundle = build_publish_bundle(
                parsed["assetRefs"],
                {**deps, "no_asset_store_init": parsed.get("dryRun")},
            )
            if not bundle.get("ok"):
                return write(
                    _publish_failure(
                        bundle["reason"],
                        bundle["message"],
                        retryable=False,
                        gates=bundle.get("gates"),
                    ),
                    1,
                )
            initial_blocked = _write_blocked_publish_result(bundle, parsed, write)
            if initial_blocked is not None:
                return initial_blocked

            message = _build_publish_message(
                bundle["sanitized"],
                deps,
                preview=bool(parsed.get("dryRun")),
            )
            _sync_bundle_from_publish_message(bundle, message)
            final_blocked = _write_blocked_publish_result(bundle, parsed, write)
            if final_blocked is not None:
                return final_blocked

            if parsed.get("dryRun"):
                validation = await _post_validate(message, deps)
                credits = _extract_credits(validation.get("body"))
                if not validation.get("ok"):
                    reason = _publish_reason_from_response(
                        int(validation.get("status") or 0),
                        validation.get("body"),
                        validation.get("reason"),
                    )
                    if reason == "quality_gate_failed":
                        gates = dict(bundle.get("gates") or {})
                        gates["quality"] = "fail"
                        block_reasons = list(bundle.get("blockReasons") or [])
                        if "quality_gate_failed" not in block_reasons:
                            block_reasons.append("quality_gate_failed")
                        bundle["blockReasons"] = block_reasons
                        bundle["gates"] = gates
                        return write(_dry_run_envelope(bundle, credits), 0)
                    return write(
                        _publish_failure(
                            reason,
                            _publish_reason_message(reason),
                            retryable=_publish_retryable(reason),
                            mode="dry_run",
                            gates=bundle.get("gates"),
                            assets=bundle.get("assets"),
                            credits=credits,
                        ),
                        1,
                    )
                return write(_dry_run_envelope(bundle, credits), 0)

            validation = await _post_validate(message, deps)
            if not validation.get("ok"):
                reason = _publish_reason_from_response(
                    int(validation.get("status") or 0),
                    validation.get("body"),
                    validation.get("reason"),
                )
                gates = dict(bundle.get("gates") or {})
                gates["quality"] = "fail"
                return write(
                    _publish_failure(
                        reason,
                        _publish_reason_message(reason),
                        retryable=_publish_retryable(reason),
                        mode="publish",
                        gates=gates,
                        assets=bundle.get("assets"),
                        credits=_extract_credits(validation.get("body")),
                    ),
                    1,
                )

            published = await _post_publish(message, deps)
            if not published.get("ok"):
                reason = _publish_reason_from_response(
                    int(published.get("status") or 0),
                    published.get("body"),
                    published.get("reason"),
                )
                return write(
                    _publish_failure(
                        reason,
                        _publish_reason_message(reason),
                        retryable=_publish_retryable(reason),
                        mode="publish",
                        gates=bundle.get("gates"),
                        assets=bundle.get("assets"),
                        credits=_extract_credits(published.get("body")),
                    ),
                    1,
                )

            decision = _publish_decision(published.get("body"))
            if decision == "quarantine":
                gates = dict(bundle.get("gates") or {})
                gates["quality"] = "fail"
                return write(
                    _publish_failure(
                        "quality_gate_failed",
                        _publish_reason_message("quality_gate_failed"),
                        retryable=False,
                        mode="publish",
                        gates=gates,
                        assets=bundle.get("assets"),
                        credits=_extract_credits(published.get("body")),
                    ),
                    1,
                )

            body = _record(published.get("body")) or {}
            payload = _record(body.get("payload")) or body
            status = _normalize_publish_status(published.get("body"))
            receipt_id = _string_field(payload, "receipt_id")
            bundle_id = _string_field(payload, "bundle_id")
            credits = _extract_credits(published.get("body")) or _credits_from_payload(payload)
            if not status:
                return write(
                    _publish_failure(
                        "internal_error",
                        "Hub publish response missing lifecycle status",
                        retryable=False,
                        mode="publish",
                        gates=bundle.get("gates"),
                        assets=bundle.get("assets"),
                        credits=credits,
                    ),
                    1,
                )
            success: dict[str, Any] = {
                "ok": True,
                "contract": PUBLISH_CONTRACT,
                "mode": "publish",
                "status": status,
                "reversibility": REVERSIBILITY,
                "assets": bundle.get("assets"),
            }
            if receipt_id:
                success["receipt_id"] = receipt_id
            if bundle_id:
                success["bundle_id"] = bundle_id
            if credits:
                success["credits"] = credits
            return write(success, 0)
        except Exception as exc:
            failure = _classify_error(exc, "publish")
            return write(
                _publish_failure(
                    failure["reason"],
                    failure["message"],
                    retryable=failure["retryable"],
                    mode="dry_run" if parsed.get("dryRun") else "publish",
                ),
                1,
            )
