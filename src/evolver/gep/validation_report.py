"""Standardized ValidationReport type for GEP.

Equivalent to ``evolver/src/gep/validationReport.js``.

Machine-readable, self-contained, and interoperable — consumable by
external Hubs or Judges for automated assessment.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any, cast

from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id
from evolver.gep.env_fingerprint import capture_env_fingerprint, env_fingerprint_key

_STDOUT_STDERR_MAX: int = 4000


def _is_finite_number(value: float | int) -> bool:
    """Match JS ``Number.isFinite`` (reject NaN / ±Inf)."""
    return math.isfinite(float(value))


def build_validation_report(
    *,
    gene_id: str | None = None,
    commands: list[str] | None = None,
    results: list[dict[str, Any]] | None = None,
    env_fp: dict[str, Any] | None = None,
    started_at: float | int | None = None,
    finished_at: float | int | None = None,
) -> dict[str, Any]:
    """Build a standardized ValidationReport from raw validation results.

    Parameters mirror the Node ``buildValidationReport({ geneId, commands,
    results, envFp, startedAt, finishedAt })`` contract.
    """
    env = env_fp if env_fp is not None else capture_env_fingerprint()
    results_list: list[dict[str, Any]] = list(results) if isinstance(results, list) else []

    if isinstance(commands, list):
        cmds_list = [str(c) if c is not None else "" for c in commands]
    else:
        cmds_list = []
        for r in results_list:
            if isinstance(r, dict) and r.get("cmd") is not None:
                cmds_list.append(str(r["cmd"]))
            else:
                cmds_list.append("")

    overall_ok = bool(results_list) and all(
        isinstance(r, dict) and bool(r.get("ok")) for r in results_list
    )

    duration_ms: int | float | None = None
    if (
        isinstance(started_at, (int, float))
        and isinstance(finished_at, (int, float))
        and _is_finite_number(started_at)
        and _is_finite_number(finished_at)
    ):
        duration_ms = finished_at - started_at

    command_entries: list[dict[str, Any]] = []
    for i, cmd in enumerate(cmds_list):
        r = results_list[i] if i < len(results_list) and isinstance(results_list[i], dict) else {}
        out = r.get("out") if r.get("out") is not None else r.get("stdout")
        err = r.get("err") if r.get("err") is not None else r.get("stderr")
        command_entries.append(
            {
                "command": str(cmd or ""),
                "ok": bool(r.get("ok")),
                "stdout": str(out or "")[:_STDOUT_STDERR_MAX],
                "stderr": str(err or "")[:_STDOUT_STDERR_MAX],
            }
        )

    report: dict[str, Any] = {
        "type": "ValidationReport",
        "schema_version": SCHEMA_VERSION,
        "id": f"vr_{int(time.time() * 1000)}",
        "gene_id": gene_id if gene_id is not None else None,
        "env_fingerprint": env,
        "env_fingerprint_key": (
            env_fingerprint_key(cast(dict[str, str], env)) if isinstance(env, dict) else "unknown"
        ),
        "commands": command_entries,
        "overall_ok": overall_ok,
        "duration_ms": duration_ms,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    report["asset_id"] = compute_asset_id(report)
    return report


def is_valid_validation_report(obj: Any) -> bool:
    """Return True if *obj* is a well-formed ValidationReport."""
    if not isinstance(obj, dict):
        return False
    if obj.get("type") != "ValidationReport":
        return False
    if not obj.get("id") or not isinstance(obj.get("id"), str):
        return False
    if not isinstance(obj.get("commands"), list):
        return False
    return isinstance(obj.get("overall_ok"), bool)


__all__ = [
    "build_validation_report",
    "is_valid_validation_report",
]
