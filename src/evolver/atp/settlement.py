"""ATP settlement ledger — local credit/debit bookkeeping.

A lightweight on-chain settlement skeleton.  In a production deployment
this would interface with a smart-contract wallet or L2 rollup.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

_LEDGER_FILENAME = "atp_ledger.json"


def _ledger_path() -> Path:
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / _LEDGER_FILENAME


def _load_ledger() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"balance": 0.0, "transactions": []}
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {"balance": 0.0, "transactions": []}


def _save_ledger(ledger: dict[str, Any]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _add_tx(ledger: dict[str, Any], amount: float, kind: str, reason: str) -> dict[str, Any]:
    tx = {
        "id": f"tx_{int(time.time() * 1000)}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "amount": round(amount, 6),
        "reason": reason,
    }
    ledger["transactions"].append(tx)
    return tx


def get_balance() -> dict[str, Any]:
    ledger = _load_ledger()
    return {"ok": True, "balance": ledger["balance"]}


def credit(amount: float, reason: str = "deposit") -> dict[str, Any]:
    if amount <= 0:
        return {"ok": False, "error": "Amount must be positive"}
    ledger = _load_ledger()
    ledger["balance"] = round(ledger["balance"] + amount, 6)
    _add_tx(ledger, amount, "credit", reason)
    _save_ledger(ledger)
    return {"ok": True, "balance": ledger["balance"]}


def debit(amount: float, reason: str = "payment") -> dict[str, Any]:
    if amount <= 0:
        return {"ok": False, "error": "Amount must be positive"}
    ledger = _load_ledger()
    if ledger["balance"] < amount:
        return {"ok": False, "error": "Insufficient balance"}
    ledger["balance"] = round(ledger["balance"] - amount, 6)
    _add_tx(ledger, amount, "debit", reason)
    _save_ledger(ledger)
    return {"ok": True, "balance": ledger["balance"]}


def history(limit: int = 20) -> dict[str, Any]:
    ledger = _load_ledger()
    txs = list(reversed(ledger.get("transactions", [])))
    return {"ok": True, "transactions": txs[:limit]}
