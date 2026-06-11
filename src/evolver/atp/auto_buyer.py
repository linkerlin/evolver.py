"""ATP auto-buyer — autonomous capability-gap buyer.

Equivalent to ``evolver/src/atp/autoBuyer.js``.
Opt-in. Daily budget cap, per-order cap, 24h dedup, cold-start halving.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC
from pathlib import Path
from typing import Any, cast

from evolver.atp.hub_client import place_order
from evolver.atp.question_composer import compose
from evolver.gep.paths import get_memory_dir

logger = logging.getLogger(__name__)

_ACK_FILENAME = "atp-auto-buy-ack.json"
_LEDGER_FILENAME = "atp-autobuyer-ledger.json"
_DAILY_BUDGET_DEFAULT = 50.0
_PER_ORDER_CAP_DEFAULT = 10.0
_COLD_START_MINUTES = 5


def _ack_path() -> Path:
    return get_memory_dir() / _ACK_FILENAME


def get_consent() -> dict[str, Any] | None:
    env = os.environ.get("EVOLVER_ATP_AUTOBUY", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return {"enabled": True, "source": "env"}
    if env in ("0", "false", "no", "off"):
        return {"enabled": False, "source": "env"}
    p = _ack_path()
    if p.exists():
        try:
            return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def set_consent(enabled: bool) -> bool:
    p = _ack_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": enabled,
        "acknowledged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": 1,
    }
    tmp = p.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.replace(p)
    except OSError:
        if p.exists():
            p.unlink()
        tmp.replace(p)
    return True


def _ledger_path() -> Path:
    return get_memory_dir() / _LEDGER_FILENAME


def _read_ledger() -> dict[str, Any]:
    p = _ledger_path()
    if not p.exists():
        return {"version": 1, "day_key": "", "spent": 0.0, "dedup": {}}
    try:
        return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "day_key": "", "spent": 0.0, "dedup": {}}


def _write_ledger(ledger: dict[str, Any]) -> None:
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _question_hash(capabilities: list[str], question: str) -> str:
    return hashlib.sha256(("|".join(capabilities) + "::" + question).encode("utf-8")).hexdigest()[
        :24
    ]


_GAP_KEYWORDS: dict[str, list[str]] = {
    "debugging": ["typeerror", "attributeerror", "exception", "traceback", "failed", "error"],
    "code_review": ["review", "lint", "ruff", "mypy", "quality"],
    "refactoring": ["refactor", "duplicate", "complexity", "smell"],
    "testing": ["pytest", "test failed", "coverage", "assertion"],
    "translation": ["translate", "i18n", "localization", "locale"],
    "summarization": ["summarize", "digest", "tl;dr", "summary"],
}


def detect_capability_gaps(signals: list[str]) -> list[dict[str, str]]:
    """Map runtime signals to ATP capability gaps worth ordering."""
    if not signals:
        return []
    blob = " ".join(signals).lower()
    gaps: list[dict[str, str]] = []
    seen: set[str] = set()
    for capability, keywords in _GAP_KEYWORDS.items():
        if capability in seen:
            continue
        for kw in keywords:
            if kw in blob:
                gaps.append({"capability": capability, "signal": kw})
                seen.add(capability)
                break
    return gaps


def _effective_cap() -> float:
    consent = get_consent()
    if not consent or not consent.get("enabled"):
        return 0.0
    daily = float(os.environ.get("EVOLVER_ATP_DAILY_BUDGET", str(_DAILY_BUDGET_DEFAULT)))
    per_order = float(os.environ.get("EVOLVER_ATP_PER_ORDER_BUDGET", str(_PER_ORDER_CAP_DEFAULT)))
    # Cold-start halving
    ack_time = consent.get("acknowledged_at", "")
    if ack_time:
        try:
            from datetime import datetime

            t = datetime.fromisoformat(ack_time.replace("Z", "+00:00"))
            mins = (datetime.now(UTC) - t).total_seconds() / 60
            if mins < _COLD_START_MINUTES:
                daily /= 2
                per_order /= 2
        except Exception:
            pass
    return min(daily, per_order)


async def consider_order(
    capabilities: list[str],
    signal: str = "",
    service_id: str = "",
    budget: float | None = None,
) -> dict[str, Any]:
    """Main entry: decide whether to place an order."""
    consent = get_consent()
    if not consent or not consent.get("enabled"):
        return {"ok": False, "error": "auto_buyer_disabled"}

    question = compose(capabilities, signal)
    qhash = _question_hash(capabilities, question)

    ledger = _read_ledger()
    today = _day_key()
    if ledger.get("day_key") != today:
        ledger = {"version": 1, "day_key": today, "spent": 0.0, "dedup": {}}

    dedup = ledger.get("dedup", {})
    prev = dedup.get(qhash)
    if prev:
        elapsed = time.time() - prev.get("ts", 0)
        if not prev.get("failed") and elapsed < 86400:
            return {"ok": False, "error": "dedup_24h"}
        if prev.get("failed") and elapsed < 300:
            return {"ok": False, "error": "dedup_5min_retry"}

    cap = _effective_cap()
    if cap <= 0:
        return {"ok": False, "error": "budget_cap_zero"}

    order_budget = min(budget or cap, cap)
    if ledger["spent"] + order_budget > cap * 2:  # soft daily ceiling
        return {"ok": False, "error": "daily_budget_exceeded"}

    result = await place_order(
        service_id or "auto", order_budget, {"question": question, "capabilities": capabilities}
    )
    if result.get("ok"):
        ledger["spent"] = round(ledger["spent"] + order_budget, 6)
        dedup[qhash] = {"ts": time.time(), "failed": False}
    else:
        dedup[qhash] = {"ts": time.time(), "failed": True}
    ledger["dedup"] = dedup
    _write_ledger(ledger)
    return result


async def run_tick(
    signals: list[str] | None = None,
    *,
    max_orders: int = 3,
) -> dict[str, Any]:
    """Evaluate signal gaps and place up to *max_orders* ATP orders."""
    consent = get_consent()
    if not consent or not consent.get("enabled"):
        return {"ok": False, "error": "auto_buyer_disabled", "orders": []}

    gaps = detect_capability_gaps(signals or [])
    if not gaps:
        return {"ok": True, "orders": [], "message": "no_capability_gaps"}

    orders: list[dict[str, Any]] = []
    for gap in gaps[: max(1, max_orders)]:
        result = await consider_order(
            [gap["capability"]],
            signal=gap.get("signal", ""),
        )
        orders.append({"gap": gap, "result": result})
        if not result.get("ok") and result.get("error") in (
            "daily_budget_exceeded",
            "budget_cap_zero",
            "dedup_24h",
        ):
            break

    placed = sum(1 for o in orders if o["result"].get("ok"))
    return {"ok": True, "orders": orders, "placed": placed, "gaps_seen": len(gaps)}
