"""Solidify process helpers (v1.94.0 parity).

Behavioral port of the helper cluster of Node ``src/gep/solidify-helpers.js``
(contract: ``test/solidify-helpers.test.js``): blast-radius severity
classification, breakdown grouping, drift comparison, failure-reason
composition, process scoring, category picking, and the forbidden-path guard.

Validation-command gating lives in :mod:`evolver.gep.policy_check`
(``is_validation_command_allowed``) and is shared with the publish path.
"""

from __future__ import annotations

from typing import Any

from evolver.config import BLAST_RADIUS_HARD_CAP_FILES, BLAST_RADIUS_HARD_CAP_LINES
from evolver.gep.git_ops import is_constraint_counted_path, normalize_rel_path

VALID_CATEGORIES = frozenset({"repair", "optimize", "innovate", "explore"})
DEFAULT_GENE_CATEGORY = "innovate"

_APPROACHING_RATIO = 0.8
_CRITICAL_OVERRUN_RATIO = 2.0
_DRIFT_RATIO = 3.0

# Paths that count as "GEP metadata" for the hollow-commit guard.
_GEP_METADATA_PREFIXES = ("assets/gep/", ".evolver/")


def is_forbidden_path(rel_path: str, forbidden: list[str] | None) -> bool:
    """True when *rel_path* equals or starts with an entry in *forbidden*."""
    p = normalize_rel_path(rel_path)
    return any(p == entry or p.startswith(f"{entry}/") for entry in forbidden or [])


def classify_blast_severity(
    *,
    blast: dict[str, Any],
    max_files: int,
    max_lines: int | None = None,
) -> str:
    """Classify blast-radius size against gene + system limits.

    Severity ladder (Node parity): ``hard_cap_breach`` (above system caps) >
    ``critical_overrun`` (>= 2x gene cap) > ``exceeded`` (> gene cap) >
    ``approaching_limit`` (> 80% of gene cap) > ``within_limit``.
    """
    files = int(blast.get("files") or 0)
    lines = int(blast.get("lines") or 0)
    if files > BLAST_RADIUS_HARD_CAP_FILES or (
        max_lines is not None and lines > BLAST_RADIUS_HARD_CAP_LINES
    ):
        return "hard_cap_breach"
    if files >= max_files * _CRITICAL_OVERRUN_RATIO:
        return "critical_overrun"
    if files > max_files:
        return "exceeded"
    if files >= max_files * _APPROACHING_RATIO:
        return "approaching_limit"
    return "within_limit"


def analyze_blast_radius_breakdown(files: list[str], top_n: int) -> list[dict[str, Any]]:
    """Group changed files by top-level directory, most-touched first."""
    counts: dict[str, int] = {}
    for f in files:
        top = normalize_rel_path(f).split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"dir": d, "files": n} for d, n in ranked[: max(0, top_n)]]


def compare_blast_estimate(
    estimate: dict[str, Any] | None,
    actual: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare actual blast to the pre-mutation estimate; None when absent."""
    if not isinstance(estimate, dict):
        return None
    est_files = int(estimate.get("files") or 0)
    act_files = int(actual.get("files") or 0)
    if est_files <= 0:
        return {"drifted": act_files > 0}
    return {"drifted": act_files >= est_files * _DRIFT_RATIO}


def build_failure_reason(
    constraint_report: dict[str, Any],
    validation: dict[str, Any],
    protocol_violations: list[str] | None,
    canary: dict[str, Any] | None,
) -> str:
    """Compose a human-readable failure reason; ``unknown`` when nothing failed."""
    parts: list[str] = []
    violations = (
        constraint_report.get("violations")
        if isinstance(constraint_report, dict)
        and isinstance(constraint_report.get("violations"), list)
        else []
    )
    for v in violations:
        parts.append(f"constraint: {v}")
    results_raw = validation.get("results") if isinstance(validation, dict) else None
    if isinstance(results_raw, list) and any(
        not r.get("ok") for r in results_raw if isinstance(r, dict)
    ):
        parts.append("validation_failed")
    for pv in protocol_violations or []:
        parts.append(f"protocol: {pv}")
    if isinstance(canary, dict) and canary.get("ok") is False:
        parts.append("canary_failed")
    return "; ".join(parts) if parts else "unknown"


def _validation_pass_rate(validation: dict[str, Any]) -> float:
    results = validation.get("results")
    if isinstance(results, list) and results:
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
        return ok / len(results)
    if isinstance(validation, dict) and validation.get("ok") is True:
        return 0.5
    return 0.0


def _hollow_commit(constraint_report: dict[str, Any], blast: dict[str, Any]) -> bool:
    if isinstance(constraint_report, dict) and any(
        str(v).startswith("hollow_commit")
        for v in (constraint_report.get("violations") or [])
    ):
        return True
    all_changed = blast.get("all_changed_files")
    if not isinstance(all_changed, list) or not all_changed:
        return False
    counted = [
        f
        for f in all_changed
        if isinstance(f, str)
        and is_constraint_counted_path(f)
        and not f.startswith(_GEP_METADATA_PREFIXES)
    ]
    return len(counted) == 0


def compute_process_scores(
    *,
    constraint_check: dict[str, Any],
    validation: dict[str, Any],
    protocol_violations: list[str] | None,
    canary: dict[str, Any] | None,
    blast: dict[str, Any],
    gene_used: dict[str, Any],
    signals: list[str] | None,
    mutation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute process metrics (validation_pass_rate, blast_control, ...)."""
    rate = _validation_pass_rate(validation)
    hollow = _hollow_commit(constraint_check, blast)
    blast_control = 0.0 if hollow else 1.0
    scores: dict[str, Any] = {
        "validation_pass_rate": rate,
        "blast_control": blast_control,
        "hollow_commit": hollow,
    }
    scores["effective_population_size"] = max(
        1, int(gene_used.get("effectivePopulationSize") or 0) or len(signals or [])
    )
    return scores


def pick_gene_category(intent: Any, fallback: str = DEFAULT_GENE_CATEGORY) -> str:
    """Return *intent* when it is a valid category, else a safe fallback."""
    if isinstance(intent, str) and intent in VALID_CATEGORIES:
        return intent
    if fallback in VALID_CATEGORIES:
        return fallback
    return DEFAULT_GENE_CATEGORY


__all__ = [
    "analyze_blast_radius_breakdown",
    "build_failure_reason",
    "classify_blast_severity",
    "compare_blast_estimate",
    "compute_process_scores",
    "is_forbidden_path",
    "pick_gene_category",
]
