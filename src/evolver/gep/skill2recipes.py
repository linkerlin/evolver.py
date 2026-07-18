"""Compose verified Skills into Hub GEP Recipes.

Equivalent to ``evolver/src/gep/skill2recipes.js``.  This module is distinct
from :mod:`evolver.recipe`, which installs file-template recipes.
"""

# Direct port orchestrators intentionally use fail-fast return branches.
# ruff: noqa: PLR0911, PLR0912

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx

from evolver.gep import a2a_protocol, asset_store
from evolver.gep.content_hash import compute_asset_id
from evolver.gep.paths import get_memory_dir, get_repo_root
from evolver.gep.skill2gep import parse_skill_md, skill_to_gene_dict
from evolver.gep.skill2gep_audit import (
    build_private_vocab,
    find_leakage,
    redact_private_literals,
)

LOG_FILE = "skill2recipes_log.jsonl"
STATE_FILE = "skill2recipes_state.json"
VALIDATION_TIMEOUT_SECONDS = 180
RECIPE_TIMEOUT_SECONDS = 20
MAX_STEPS = 20

_ALLOWED_VALIDATION_EXECUTABLES = frozenset(
    {"node", "npm", "npx", "python", "python3", "pytest", "uv"}
)
_VALIDATION_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:validation|validate|verification|验证|校验)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FENCED_BLOCK_RE = re.compile(r"```(?:bash|sh|shell|powershell|cmd)?\s*\n(.*?)```", re.DOTALL)


def log_path() -> Path:
    return get_memory_dir() / LOG_FILE


def state_path() -> Path:
    return get_memory_dir() / STATE_FILE


def _short_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode()).hexdigest()[:12]


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"recipes": {}}
    except (OSError, json.JSONDecodeError):
        return {"recipes": {}}


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_manifest(
    manifest: Any,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize object, ``skills`` alias, or bare path-array manifests."""
    options = opts or {}
    source = {"steps": manifest} if isinstance(manifest, list) else manifest
    source = source if isinstance(source, dict) else {}
    raw_steps = source.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = source.get("skills")
    if not isinstance(raw_steps, list):
        raw_steps = []

    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_steps):
        step = {"skill_path": raw} if isinstance(raw, str) else raw
        step = step if isinstance(step, dict) else {}
        position = step.get("position")
        steps.append(
            {
                "skill_path": step.get("skill_path")
                or step.get("skillPath")
                or step.get("path"),
                "skill_name": step.get("skill_name") or step.get("skillName"),
                "platform": step.get("platform"),
                "position": position if isinstance(position, int) else index,
                "optional": bool(step.get("optional")),
                "condition": (
                    str(step["condition"]) if step.get("condition") is not None else None
                ),
                "parameters": step.get("parameters"),
            }
        )

    price = (
        options["price_per_execution"]
        if options.get("price_per_execution") is not None
        else options["pricePerExecution"]
        if options.get("pricePerExecution") is not None
        else source.get("price_per_execution")
    )
    return {
        "title": options.get("title") or source.get("title"),
        "description": options.get("description") or source.get("description") or "",
        "price_per_execution": price,
        "currency": source.get("currency"),
        "max_concurrent": source.get("max_concurrent"),
        "input_schema": source.get("input_schema"),
        "output_schema": source.get("output_schema"),
        "steps": steps,
    }


def _validation_section(markdown: str) -> str:
    match = _VALIDATION_HEADING_RE.search(markdown)
    if not match:
        return ""
    rest = markdown[match.end() :]
    next_heading = re.search(r"^#{1,6}\s+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def _extract_validation_commands(markdown: str) -> list[str]:
    commands: list[str] = []
    for block in _FENCED_BLOCK_RE.findall(_validation_section(markdown)):
        for line in block.splitlines():
            command = line.strip()
            if command and not command.startswith("#"):
                commands.append(command)
    return commands


def _validation_argv(command: str) -> list[str] | None:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not argv:
        return None
    executable = Path(argv[0]).name.lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in _ALLOWED_VALIDATION_EXECUTABLES:
        return None
    if any(token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "$(")):
        return None
    return argv


def _run_validations(
    commands: list[str],
    *,
    repo_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for command in commands:
        argv = _validation_argv(command)
        if argv is None:
            results.append(
                {"cmd": command, "ok": False, "out": "", "err": "validation_not_allowed"}
            )
            continue
        try:
            completed = subprocess.run(
                argv,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            results.append(
                {
                    "cmd": command,
                    "ok": completed.returncode == 0,
                    "out": completed.stdout,
                    "err": completed.stderr,
                }
            )
        except (OSError, subprocess.SubprocessError) as exc:
            results.append({"cmd": command, "ok": False, "out": "", "err": str(exc)})
    return {"ok": bool(results) and all(row["ok"] for row in results), "results": results}


def hydrolyze_and_verify(
    step: dict[str, Any],
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hydrolyze one Skill and require real allow-listed validation evidence."""
    options = opts or {}
    raw_path = step.get("skill_path")
    skill_path = Path(raw_path) if isinstance(raw_path, (str, Path)) else None
    if skill_path is None or not skill_path.exists():
        return {
            "ok": False,
            "diagnostic": {"reason": "skill_path_missing", "skill_path": raw_path},
        }
    try:
        skill_md_path = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
    except OSError:
        return {
            "ok": False,
            "diagnostic": {"reason": "skill_path_unreadable", "skill_path": str(skill_path)},
        }
    if not skill_md_path.exists():
        return {
            "ok": False,
            "diagnostic": {"reason": "skill_md_missing", "tried": str(skill_md_path)},
        }
    try:
        markdown = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return {"ok": False, "diagnostic": {"reason": "skill_md_read_failed"}}

    parsed = parse_skill_md(markdown)
    commands = _extract_validation_commands(markdown)
    allowed_commands = [command for command in commands if _validation_argv(command) is not None]
    strict = options.get("strict", True) is not False
    if strict and (not commands or len(allowed_commands) != len(commands)):
        return {
            "ok": False,
            "diagnostic": {
                "reason": "gene_validation_failed",
                "errors": ["real allow-listed validation command required"],
            },
        }
    if not allowed_commands:
        allowed_commands = ["python --version"]

    gene = skill_to_gene_dict(skill_md_path)
    if gene is None:
        return {
            "ok": False,
            "diagnostic": {"reason": "gene_validation_failed", "errors": ["invalid skill"]},
        }
    gene["validation"] = allowed_commands
    if step.get("skill_name"):
        source = gene.get("_source")
        if isinstance(source, dict):
            source["skill_name"] = step["skill_name"]

    repo_root = Path(
        options.get("repo_root")
        or options.get("repoRoot")
        or get_repo_root()
        or Path.cwd()
    )
    runner = options.get("run_validations")
    validation = (
        runner(gene, repo_root)
        if callable(runner)
        else _run_validations(
            allowed_commands,
            repo_root=repo_root,
            timeout_seconds=int(
                options.get("validation_timeout_seconds") or VALIDATION_TIMEOUT_SECONDS
            ),
        )
    )
    results = validation.get("results") if isinstance(validation, dict) else []
    results = results if isinstance(results, list) else []
    trace = [
        {
            "step": index,
            "cmd": str(row.get("cmd") or ""),
            "exit": 0 if row.get("ok") else 1,
            "stdout_tail": str(row.get("out") or row.get("err") or "")[-300:],
        }
        for index, row in enumerate(results, start=1)
        if isinstance(row, dict)
    ]
    if not validation.get("ok"):
        return {
            "ok": False,
            "gene": gene,
            "diagnostic": {
                "reason": "validation_failed",
                "failed": [row["cmd"] for row in trace if row["exit"] != 0],
            },
        }
    execution = {"status": "success", "score": 0.85, "trace": trace}
    private_vocab = build_private_vocab(markdown, execution)
    if find_leakage(gene, private_vocab):
        gene = redact_private_literals(gene, private_vocab)
        if strict and not gene.get("validation"):
            return {
                "ok": False,
                "gene": gene,
                "diagnostic": {
                    "reason": "gene_validation_failed",
                    "errors": ["leak audit removed all validation commands"],
                },
            }

    skill_name = parsed.name or str(gene.get("id") or "skill")
    capsule = {
        "type": "Capsule",
        "id": f"capsule_s2r-{_short_hash(str(gene.get('id')) + markdown)}",
        "schema_version": "1.8.0",
        "trigger": list(gene.get("signals_match") or [])[:6],
        "gene": gene.get("id"),
        "summary": (
            f'Verified skill "{skill_name}": '
            f"{sum(row['exit'] == 0 for row in trace)}/{len(trace)} validation command(s) passed."
        ),
        "confidence": 0.85,
        "blast_radius": {"files": max(1, len(trace)), "lines": len(trace)},
        "outcome": {"status": "success", "score": 0.85},
        "success_reason": "All declared validation commands exited 0 in repoRoot.",
        "execution_trace": trace,
    }
    return {
        "ok": True,
        "gene": gene,
        "capsule": capsule,
        "skill_name": skill_name,
        "skill_hash": _short_hash(markdown),
        "execution": execution,
    }


async def publish_step_bundle(
    gene: dict[str, Any],
    capsule: dict[str, Any],
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist and optionally publish a verified Gene+Capsule bundle."""
    options = opts or {}
    gene_copy = copy.deepcopy(gene)
    capsule_copy = copy.deepcopy(capsule)
    gene_copy["asset_id"] = compute_asset_id(gene_copy)
    capsule_copy["asset_id"] = compute_asset_id(capsule_copy)
    capsule_copy["gene"] = gene_copy["asset_id"]
    capsule_copy["asset_id"] = compute_asset_id(capsule_copy)

    store = options.get("asset_store") or asset_store
    persist_errors: list[dict[str, str]] = []
    for operation, value in (("upsert_gene", gene_copy), ("append_capsule", capsule_copy)):
        try:
            getattr(store, operation)(value)
        except Exception:
            persist_errors.append({"step": operation, "error": "local persistence failed"})

    result = {
        "gene_asset_id": gene_copy["asset_id"],
        "capsule_asset_id": capsule_copy["asset_id"],
        "persist_errors": persist_errors,
    }
    if options.get("publish", True) is False:
        return {
            "ok": True,
            **result,
            "publish": {"skipped": "publish_disabled"},
        }

    protocol = options.get("a2a") or a2a_protocol
    try:
        message = protocol.build_publish_bundle(
            gene=gene_copy,
            capsule=capsule_copy,
            node_id=protocol.get_node_id(),
        )
    except Exception:
        return {"ok": False, "reason": "build_publish_bundle_failed", **result}

    sender = options.get("send_publish")
    if callable(sender):
        sent = sender(message)
        if asyncio.iscoroutine(sent):
            sent = await sent
    else:
        sent = await asyncio.to_thread(
            protocol.post_hub_envelope,
            "/a2a/publish",
            message,
            hub_url=protocol.get_hub_url(),
            headers=protocol.build_node_scoped_hub_headers(),
            timeout_ms=15000,
        )
    return {"ok": bool(sent and sent.get("ok")), **result, "publish": sent}


async def post_recipe(
    recipe_body: dict[str, Any],
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and publish a Hub Recipe REST resource."""
    options = opts or {}
    if options.get("publish", True) is False:
        return {
            "ok": True,
            "recipe_id": None,
            "dry_run": True,
            "body": recipe_body,
            "publish": {"skipped": "publish_disabled"},
        }
    poster = options.get("recipe_poster")
    if callable(poster):
        value = poster(recipe_body)
        return cast(dict[str, Any], await value if asyncio.iscoroutine(value) else value)

    protocol = options.get("a2a") or a2a_protocol
    hub_url = protocol.get_hub_url()
    if not hub_url:
        return {"ok": False, "reason": "no_hub_url"}
    base = hub_url.rstrip("/")
    headers = protocol.build_node_scoped_hub_headers()
    try:
        async with httpx.AsyncClient(timeout=RECIPE_TIMEOUT_SECONDS) as client:
            created = await client.post(f"{base}/a2a/recipe", headers=headers, json=recipe_body)
            try:
                create_body = created.json()
            except json.JSONDecodeError:
                create_body = {"raw": created.text[:200]}
            if not created.is_success:
                return {
                    "ok": False,
                    "reason": "recipe_create_failed",
                    "status": created.status_code,
                    "body": create_body,
                }
            root = create_body if isinstance(create_body, dict) else {}
            recipe = cast(
                dict[str, Any],
                root.get("recipe") if isinstance(root.get("recipe"), dict) else {},
            )
            recipe_id = recipe.get("id") or recipe.get("recipe_id")
            if not recipe_id:
                return {"ok": False, "reason": "recipe_id_missing", "create": create_body}
            published = await client.post(
                f"{base}/a2a/recipe/{quote(str(recipe_id), safe='')}/publish",
                headers=headers,
                json={"sender_id": recipe_body["sender_id"]},
            )
            try:
                publish_body = published.json()
            except json.JSONDecodeError:
                publish_body = {"raw": published.text[:200]}
            if not published.is_success:
                return {
                    "ok": False,
                    "reason": "recipe_publish_failed",
                    "recipe_id": recipe_id,
                    "status": published.status_code,
                    "body": publish_body,
                    "create": create_body,
                }
            return {
                "ok": True,
                "recipe_id": recipe_id,
                "create": create_body,
                "publish": publish_body,
            }
    except httpx.HTTPError:
        return {"ok": False, "reason": "recipe_create_request_failed"}


async def compose_recipe_from_skills(
    manifest: Any,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hydrolyze, verify, publish, and compose all manifest steps in order."""
    options = opts or {}
    normalized = normalize_manifest(manifest, options)
    title = normalized.get("title")
    if not isinstance(title, str) or len(title.strip()) < 3:
        return {"ok": False, "reason": "title_min_3_chars"}
    steps = normalized["steps"]
    if not steps:
        return {"ok": False, "reason": "no_steps"}
    if len(steps) > MAX_STEPS:
        return {"ok": False, "reason": "too_many_steps", "max": MAX_STEPS, "got": len(steps)}

    recipe_steps: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    publish_results: list[dict[str, Any]] = []
    hydrolyzer = options.get("hydrolyze") or hydrolyze_and_verify
    publisher = options.get("publish_bundle") or publish_step_bundle
    log_target = Path(options.get("log_path") or log_path())

    for step in steps:
        verified = hydrolyzer(step, options)
        if not verified.get("ok"):
            if step["optional"]:
                skipped.append(
                    {"skill_path": step["skill_path"], "reason": verified.get("diagnostic")}
                )
                _append_jsonl(
                    log_target,
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "status": "step_skipped_optional",
                        "skill_path": step["skill_path"],
                        "diagnostic": verified.get("diagnostic"),
                    },
                )
                continue
            return {
                "ok": False,
                "reason": "step_failed",
                "skill_path": step["skill_path"],
                "diagnostic": verified.get("diagnostic"),
                "steps_done": recipe_steps,
            }

        published = publisher(verified["gene"], verified["capsule"], options)
        if asyncio.iscoroutine(published):
            published = await published
        publish_results.append(
            {
                "skill_path": step["skill_path"],
                "gene_id": verified["gene"].get("id"),
                "result": published,
            }
        )
        if not published.get("ok") and options.get("publish", True) is not False:
            if step["optional"]:
                skipped.append(
                    {
                        "skill_path": step["skill_path"],
                        "reason": {"reason": "gene_publish_failed", "detail": published},
                    }
                )
                continue
            return {
                "ok": False,
                "reason": "gene_publish_failed",
                "skill_path": step["skill_path"],
                "detail": published,
                "steps_done": recipe_steps,
            }
        recipe_steps.append(
            {
                "asset_id": published["gene_asset_id"],
                "asset_type": "Gene",
                "position": len(recipe_steps),
                "optional": step["optional"],
                "condition": step["condition"],
                "parameters": step["parameters"],
                "_skill_path": step["skill_path"],
                "_capsule_asset_id": published["capsule_asset_id"],
            }
        )

    if not recipe_steps:
        return {"ok": False, "reason": "all_steps_skipped", "skipped": skipped}

    protocol = options.get("a2a") or a2a_protocol
    recipe_body: dict[str, Any] = {
        "sender_id": protocol.get_node_id() or a2a_protocol.DRY_RUN_NODE_ID,
        "title": title,
        "steps": [
            {
                key: step[key]
                for key in (
                    "asset_id",
                    "asset_type",
                    "position",
                    "optional",
                    "condition",
                    "parameters",
                )
            }
            for step in recipe_steps
        ],
    }
    for key in (
        "description",
        "price_per_execution",
        "currency",
        "max_concurrent",
        "input_schema",
        "output_schema",
    ):
        if normalized.get(key) not in (None, ""):
            recipe_body[key] = normalized[key]

    recipe_result = await post_recipe(recipe_body, options)
    state_target = Path(options.get("state_path") or state_path())
    state = _read_state(state_target)
    recipes = state.setdefault("recipes", {})
    state_key = _short_hash(
        title + "|" + ",".join(str(step["asset_id"]) for step in recipe_steps)
    )
    recipes[state_key] = {
        "at": datetime.now(UTC).isoformat(),
        "title": title,
        "recipe_id": recipe_result.get("recipe_id"),
        "step_asset_ids": [step["asset_id"] for step in recipe_steps],
        "published": bool(recipe_result.get("ok")),
    }
    errors: list[dict[str, str]] = []
    try:
        _write_state(state_target, state)
    except OSError:
        errors.append({"step": "write_state", "error": "state write failed"})

    return {
        "ok": bool(recipe_result.get("ok")),
        "recipe_id": recipe_result.get("recipe_id"),
        "title": title,
        "market_url": (
            "https://evomap.ai/market?tab=recipes"
            if recipe_result.get("recipe_id")
            else None
        ),
        "steps": [
            {
                "skill_path": step["_skill_path"],
                "asset_id": step["asset_id"],
                "asset_type": step["asset_type"],
                "position": step["position"],
                "optional": step["optional"],
                "condition": step["condition"],
                "capsule_asset_id": step["_capsule_asset_id"],
            }
            for step in recipe_steps
        ],
        "skipped": skipped,
        "gene_publish": publish_results,
        "recipe": recipe_result,
        "errors": errors,
    }


__all__ = [
    "LOG_FILE",
    "MAX_STEPS",
    "STATE_FILE",
    "compose_recipe_from_skills",
    "hydrolyze_and_verify",
    "log_path",
    "normalize_manifest",
    "post_recipe",
    "publish_step_bundle",
    "state_path",
]
