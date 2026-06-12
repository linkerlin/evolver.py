"""Autopoiesis guard rules — load encoded friction → signal keys.

Reads ``autopoiesis_rules.json`` produced by ``SelfReport.auto_encode`` and
exposes guard check signal keys for the signals / select pipeline.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.asset_store import read_json_if_exists
from evolver.gep.paths import get_gep_assets_dir


def rules_path() -> Any:
    return get_gep_assets_dir() / "autopoiesis_rules.json"


def load_autopoiesis_rules() -> dict[str, Any]:
    data = read_json_if_exists(rules_path())
    if not isinstance(data, dict):
        return {"version": "1.0.0", "guard_checks": {}, "autopoiesis": {}}
    data.setdefault("guard_checks", {})
    data.setdefault("autopoiesis", {})
    return data


def guard_check_signal_keys() -> list[str]:
    """Return active ``signal_key`` values from autopoiesis guard_checks."""
    rules = load_autopoiesis_rules()
    checks = rules.get("guard_checks") or {}
    keys: list[str] = []
    if not isinstance(checks, dict):
        return keys
    for entry in checks.values():
        if not isinstance(entry, dict):
            continue
        key = entry.get("signal_key")
        if isinstance(key, str) and key and key not in keys:
            keys.append(key)
    return keys


def merge_signal_keys(signals: list[str], extra: list[str]) -> tuple[list[str], list[str]]:
    """Append unique keys; return (merged_signals, newly_added)."""
    merged = list(signals)
    added: list[str] = []
    for key in extra:
        if key not in merged:
            merged.append(key)
            added.append(key)
    return merged, added
