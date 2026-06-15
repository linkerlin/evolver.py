"""Autopoiesis orchestrator — SelfReport + living memory + homeostasis.

Faithful port of md2video Autopoiesis governance:

* **Self-observation** — ``SelfReport.load_system_state()`` reads GEP assets.
* **Friction capture** — pipeline failures encoded into guard rules + pending signals.
* **Living memory** — ``LESSONS_LEARNED.md`` YAML frontmatter (``living_memory``).
* **Homeostasis** — viability score regulates drift / repair bias per cycle.

See md2video ``harness/self_report.py`` and ``harness/memory_loader.py``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.gep.asset_store import atomic_write_json, read_json_if_exists
from evolver.gep.autopoiesis_rules import guard_check_signal_keys, merge_signal_keys
from evolver.gep.living_memory import format_guard_items, format_risk_warnings, load_living_memory
from evolver.gep.paths import get_evolution_dir
from evolver.gep.self_report import SelfReport

logger = logging.getLogger(__name__)

AUTOPOIESIS_LOG_ENV = "EVOLVER_AUTOPOIESIS_LOG_PATH"
AUTOPOIESIS_STATE_FILE = "autopoiesis_state.json"
PREFLIGHT_ABORT_FILE = "autopoiesis_preflight_abort.json"
VIABILITY_STABLE = 0.65
VIABILITY_STRESSED = 0.40


@dataclass
class ViabilityReport:
    score: float
    status: str
    boundary: float
    metabolism: float
    homeostasis: float
    coupling: float
    factors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "status": self.status,
            "boundary": round(self.boundary, 4),
            "metabolism": round(self.metabolism, 4),
            "homeostasis": round(self.homeostasis, 4),
            "coupling": round(self.coupling, 4),
            "factors": list(self.factors),
        }


def is_autopoiesis_enabled() -> bool:
    return os.environ.get("EVOLVER_AUTOPOIESIS", "1").lower() not in ("0", "false", "no", "off")


def is_autopoiesis_write_enabled() -> bool:
    return os.environ.get("EVOLVER_AUTOPOIESIS_WRITE", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _log_path() -> Path:
    override = os.environ.get(AUTOPOIESIS_LOG_ENV)
    if override:
        return Path(override)
    return get_evolution_dir() / "autopoiesis.jsonl"


def _status_for_score(score: float) -> str:
    if score >= VIABILITY_STABLE:
        return "stable"
    if score >= VIABILITY_STRESSED:
        return "stressed"
    return "critical"


def compute_viability(ctx: dict[str, Any]) -> ViabilityReport:
    """Composite health score from GEP pipeline context."""
    factors: list[str] = []

    genes = ctx.get("genes") or []
    boundary = 0.5
    if genes:
        boundary += 0.35
    else:
        factors.append("no_genes")
    try:
        from evolver.evolve.guards import check_repair_loop_circuit_breaker  # noqa: PLC0415

        breaker = check_repair_loop_circuit_breaker()
        if breaker.get("tripped"):
            boundary *= 0.3
            factors.append("repair_loop_tripped")
    except Exception:
        pass

    signals = ctx.get("signals") or []
    metabolism = 0.4
    if signals:
        metabolism += min(0.5, len(signals) * 0.08)
    else:
        factors.append("no_signals")
    if ctx.get("failure_diagnosis"):
        metabolism *= 0.7
        factors.append("session_errors")

    homeostasis = 1.0
    diag = ctx.get("failure_diagnosis")
    if isinstance(diag, dict):
        conf = float(diag.get("confidence", 0.5))
        homeostasis = max(0.2, 1.0 - conf * 0.6)
        factors.append(f"diagnosis:{diag.get('category', 'unknown')}")

    if ctx.get("preflight_abort_recovery") or read_preflight_abort_report():
        homeostasis *= 0.75
        factors.append("preflight_abort_recovery")

    memory = ctx.get("living_memory") or {}
    if memory.get("loaded") and memory.get("high_friction_points"):
        homeostasis *= 0.85
        factors.append("living_memory_risks")

    coupling = 0.5
    try:
        from evolver.ops.innovation import compute_innovation_roi

        roi = compute_innovation_roi(window_days=30, min_attempts=3)
        if not roi.get("insufficient_data") and roi.get("roi") is not None:
            if float(roi["roi"]) < 0.15:
                coupling *= 0.9
                factors.append("low_innovation_roi")
    except Exception:
        pass

    hub_hit = ctx.get("hub_hit") or {}
    reason = str(hub_hit.get("reason", ""))
    if reason in ("tasks_found", "services_found", "assets_found"):
        coupling = 0.85
    elif reason == "offline":
        coupling = 0.35
        factors.append("hub_offline")
    elif reason == "idle_skip":
        coupling = 0.55

    score = (
        0.30 * min(1.0, boundary)
        + 0.20 * min(1.0, metabolism)
        + 0.30 * min(1.0, homeostasis)
        + 0.20 * min(1.0, coupling)
    )
    return ViabilityReport(
        score=score,
        status=_status_for_score(score),
        boundary=min(1.0, boundary),
        metabolism=min(1.0, metabolism),
        homeostasis=min(1.0, homeostasis),
        coupling=min(1.0, coupling),
        factors=factors,
    )


def homeostasis_response(viability: ViabilityReport) -> dict[str, Any]:
    actions: list[str] = []
    if viability.status == "critical":
        actions.extend(["force_repair_mode", "disable_drift", "prefer_low_risk_genes"])
    elif viability.status == "stressed":
        actions.extend(["bias_repair", "limit_blast_radius"])
    else:
        actions.append("maintain")

    return {
        "status": viability.status,
        "actions": actions,
        "drift_allowed": viability.status == "stable",
        "skip_hub_recommended": (
            viability.status == "critical" and "hub_offline" in viability.factors
        ),
    }


def _state_path() -> Path:
    return get_evolution_dir() / AUTOPOIESIS_STATE_FILE


def persist_skip_hub_flag() -> None:
    """Schedule Hub skip for the next evolution cycle (homeostasis degraded mode)."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {"skip_hub_next_cycle": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    )


def consume_skip_hub_flag() -> bool:
    """Read and clear one-shot Hub skip flag."""
    path = _state_path()
    data = read_json_if_exists(path)
    if not isinstance(data, dict) or not data.get("skip_hub_next_cycle"):
        return False
    atomic_write_json(path, {"skip_hub_next_cycle": False, "consumed_ts": time.time()})
    return True


def merge_autopoiesis_signals(ctx: dict[str, Any], report: SelfReport) -> list[str]:
    """Merge guard + freshly encoded signals into ctx for same-cycle select."""
    extra: list[str] = list(guard_check_signal_keys())
    for fp in report.friction_points:
        if fp.rule_id:
            key = f"autopoiesis:{fp.rule_id}"
            if key not in extra:
                extra.append(key)
    signals, added = merge_signal_keys(list(ctx.get("signals") or []), extra)
    ctx["signals"] = signals
    if added:
        ctx["autopoiesis_signals_merged"] = added
    return added


def format_autopoiesis_context(ctx: dict[str, Any]) -> str:
    """Build prompt context block from living memory + autopoiesis homeostasis."""
    parts: list[str] = []
    warnings = ctx.get("living_memory_warnings")
    if isinstance(warnings, str) and warnings.strip():
        parts.append(warnings.strip())
    apo = ctx.get("autopoiesis") or {}
    viability = apo.get("viability") or {}
    homeostasis = apo.get("homeostasis") or {}
    if viability:
        score = float(viability.get("score", 0) or 0)
        parts.append(
            "autopoiesis_viability: "
            f"{viability.get('status', 'unknown')} "
            f"score={score:.2f}"
        )
    actions = homeostasis.get("actions") or []
    if actions:
        parts.append(f"autopoiesis_homeostasis: {', '.join(actions)}")
    for item in (ctx.get("living_memory_guard_items") or [])[:3]:
        if isinstance(item, dict) and item.get("message"):
            parts.append(str(item["message"]))
    if ctx.get("preflight_abort_recovery"):
        reason = ctx.get("preflight_abort_reason") or "previous cycle blocked"
        parts.append(
            f"preflight_abort_recovery: resolve blocker ({reason[:120]}) before innovate"
        )
    return "\n".join(parts)


def apply_homeostasis(ctx: dict[str, Any], response: dict[str, Any]) -> None:
    if not response.get("drift_allowed"):
        ctx["IS_RANDOM_DRIFT"] = False
        ctx["autopoiesis_drift_blocked"] = True
    if "force_repair_mode" in response.get("actions", []):
        ctx["autopoiesis_repair_bias"] = True
        plateau = ctx.get("plateau_override") or {}
        if not plateau.get("severity"):
            ctx["plateau_override"] = {"severity": "suggested", "source": "autopoiesis"}
    if response.get("skip_hub_recommended"):
        ctx["autopoiesis_hub_degraded"] = True
        persist_skip_hub_flag()


def capture_friction_from_ctx(report: SelfReport, ctx: dict[str, Any]) -> int:
    """Translate pipeline observations into SelfReport friction points."""
    captured = 0

    diag = ctx.get("failure_diagnosis")
    if isinstance(diag, dict) and diag.get("cause"):
        report.capture_friction(
            str(diag.get("category", "session_error")),
            str(diag["cause"]),
            str(diag.get("recommendation", "")),
        )
        captured += 1

    gate = ctx.get("hub_quality_gate") or {}
    for svc in gate.get("services") or []:
        review = (svc or {}).get("review") or {}
        if review.get("verdict") == "reject":
            report.capture_friction(
                "hub_quality",
                f"Hub service {svc.get('service_id', '?')} rejected",
                str(review.get("summary", "review before reuse")),
            )
            captured += 1

    for asset in gate.get("assets") or []:
        if asset.get("hash_valid") is False:
            report.capture_friction(
                "hub_quality",
                f"Hub asset hash invalid: {asset.get('asset_id', '?')}",
                "re-fetch or reject asset",
            )
            captured += 1

    try:
        from evolver.evolve.guards import check_repair_loop_circuit_breaker  # noqa: PLC0415

        breaker = check_repair_loop_circuit_breaker()
        if breaker.get("tripped"):
            report.capture_friction(
                "repair_loop",
                (
                    f"{breaker.get('consecutive', 0)}/{breaker.get('threshold', 0)} "
                    "consecutive failed repair cycles"
                ),
                "force repair mode and reduce blast radius",
            )
            captured += 1
    except Exception:
        pass

    hub_hit = ctx.get("hub_hit") or {}
    if str(hub_hit.get("reason", "")) == "offline":
        report.capture_friction(
            "hub_offline",
            "Hub unreachable this cycle",
            "retry with hub_fetch resilience or run offline",
        )
        captured += 1

    return captured


def record_autopoiesis_tick(
    *,
    run_id: str | None,
    viability: ViabilityReport,
    response: dict[str, Any],
    self_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "type": "AutopoiesisTick",
        "id": f"apo_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "run_id": run_id,
        "viability": viability.to_dict(),
        "homeostasis": response,
        "self_report": self_report,
    }
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    logger.info(
        "[Autopoiesis] friction=%s viability=%.2f status=%s",
        (self_report or {}).get("friction_summary", {}).get("total", 0),
        viability.score,
        viability.status,
    )
    return event


def read_latest_tick() -> dict[str, Any] | None:
    path = _log_path()
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    last = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    return last


def run_autopoiesis_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Full autopoiesis cycle aligned with md2video SelfReport governance."""
    if not is_autopoiesis_enabled():
        return ctx

    memory = ctx.get("living_memory") or load_living_memory()
    ctx["living_memory"] = memory
    ctx["living_memory_guard_items"] = format_guard_items(memory)
    warnings = format_risk_warnings(memory)
    if warnings:
        ctx["living_memory_warnings"] = warnings

    report = SelfReport()
    capture_friction_from_ctx(report, ctx)
    try:
        from evolver.gep.memory_bridge import capture_memory_graph_bans_as_friction  # noqa: PLC0415

        capture_memory_graph_bans_as_friction(report, ctx.get("memory_advice"))
    except Exception:
        pass
    wrote = is_autopoiesis_write_enabled()
    report_path, self_report_data = report.run(no_write=not wrote, print_human=False)
    if wrote:
        memory = load_living_memory()
        ctx["living_memory"] = memory
        ctx["living_memory_guard_items"] = format_guard_items(memory)
        warnings = format_risk_warnings(memory)
        if warnings:
            ctx["living_memory_warnings"] = warnings

    merge_autopoiesis_signals(ctx, report)

    viability = compute_viability(ctx)
    response = homeostasis_response(viability)
    apply_homeostasis(ctx, response)

    tick = record_autopoiesis_tick(
        run_id=ctx.get("run_id"),
        viability=viability,
        response=response,
        self_report=self_report_data,
    )

    ctx["autopoiesis"] = {
        "self_report": self_report_data,
        "living_memory": {
            "loaded": memory.get("loaded"),
            "total_friction_points": memory.get("total_friction_points", 0),
            "evolution_count": memory.get("evolution_count", 0),
            "recent_friction_points": memory.get("recent_friction_points", [])[:3],
        },
        "viability": viability.to_dict(),
        "homeostasis": response,
        "tick_id": tick["id"],
        "report_path": str(report_path) if report_path else None,
        "friction_captured_this_run": len(report.friction_points),
    }
    ctx["autopoiesis_context"] = format_autopoiesis_context(ctx)
    return ctx


def _preflight_abort_path() -> Path:
    return get_evolution_dir() / PREFLIGHT_ABORT_FILE


def persist_preflight_abort_report(report: dict[str, Any], *, reason: str) -> None:
    """Persist last preflight abort for WebUI / next-cycle awareness."""
    path = _preflight_abort_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "timestamp": time.time(),
            "reason": reason,
            "report": report,
        },
    )


def read_preflight_abort_report() -> dict[str, Any] | None:
    data = read_json_if_exists(_preflight_abort_path())
    return data if isinstance(data, dict) and data.get("report") else None


def preflight_abort_signal_keys() -> list[str]:
    """Explicit GEP signals from the last persisted preflight abort (next cycle)."""
    data = read_preflight_abort_report()
    if not data:
        return []
    keys = ["preflight_abort", "autopoiesis:preflight_abort"]
    reason = str(data.get("reason") or "").strip().lower()
    if reason:
        slug = "".join(c if c.isalnum() else "_" for c in reason)[:48].strip("_")
        if slug:
            keys.append(f"preflight_abort:{slug}")
    return keys


def apply_preflight_abort_recovery(ctx: dict[str, Any]) -> bool:
    """After preflight abort, bias the next cycle toward safe repair (not drift)."""
    signals = ctx.get("signals") or []
    if "preflight_abort" not in signals:
        return False
    ctx["preflight_abort_recovery"] = True
    ctx["autopoiesis_repair_bias"] = True
    ctx["IS_RANDOM_DRIFT"] = False
    ctx["skip_hub_calls"] = True
    ctx["hub_skip_reason"] = "preflight_abort_recovery"
    data = read_preflight_abort_report()
    if isinstance(data, dict) and data.get("reason"):
        ctx["preflight_abort_reason"] = str(data["reason"])
    return True


def clear_preflight_abort_report() -> None:
    path = _preflight_abort_path()
    if path.exists():
        path.unlink(missing_ok=True)


def run_preflight_abort_self_report(reason: str) -> dict[str, Any]:
    """Read-only SelfReport when preflight aborts; snapshot persisted for WebUI."""
    if not is_autopoiesis_enabled():
        return {}
    report = SelfReport()
    report.capture_friction(
        "preflight_abort",
        reason[:300],
        "resolve blocker before next evolution cycle",
        auto_encode=False,
    )
    _, data = report.run(no_write=True, print_human=False)
    persist_preflight_abort_report(data, reason=reason)
    logger.info("[Autopoiesis] preflight abort self-report friction=%s", reason[:80])
    return data


def capture_solidify_friction(error: str, *, last_run: dict[str, Any] | None = None) -> None:
    """Encode solidify failure as friction (closes solidify → living memory loop)."""
    if not is_autopoiesis_enabled() or not is_autopoiesis_write_enabled():
        return
    report = SelfReport()
    gene_id = (last_run or {}).get("selected_gene_id", "?")
    report.capture_friction(
        "solidify",
        f"solidify failed for gene {gene_id}: {error[:200]}",
        "review mutation, run tests, consider rollback",
    )
    report.run(no_write=False, print_human=False)


def capture_solidify_success(
    event: dict[str, Any],
    *,
    last_run: dict[str, Any] | None = None,
) -> None:
    """Record successful solidify as positive living-memory friction (no rule encode)."""
    if not is_autopoiesis_enabled() or not is_autopoiesis_write_enabled():
        return
    outcome = event.get("outcome") or {}
    if outcome.get("status") != "success":
        return
    run_data = last_run or {}
    gene_id = run_data.get("selected_gene_id", "?")
    mutation = run_data.get("mutation") or {}
    category = str(mutation.get("category") or "optimize")
    report = SelfReport()
    report.capture_friction(
        "solidify_success",
        f"gene {gene_id} solidified ({category})",
        "reuse successful mutation pattern for similar signals",
        auto_encode=False,
    )
    report.run(no_write=False, print_human=False)
    if gene_id and gene_id != "?":
        try:
            from evolver.gep.memory_graph import record_signal_gene_preference

            record_signal_gene_preference(
                gene_id=str(gene_id),
                signals=list(run_data.get("signals") or []),
                source="solidify_success",
            )
        except Exception as exc:
            logger.debug("[Autopoiesis] solidify preference skipped: %s", exc)


def run_self_report_cli(
    *,
    category: str | None = None,
    description: str | None = None,
    resolution: str | None = None,
    no_write: bool = False,
) -> dict[str, Any]:
    """CLI entry — mirrors ``python harness/self_report.py``."""
    report = SelfReport()
    if category and description:
        report.capture_friction(category, description, resolution or "")
    _, data = report.run(no_write=no_write, print_human=not no_write)
    return data
