"""D7 — key-module import smoke test (防「只留 pyc」回归).

Ensures the modules that once regressed to bytecode-only (A14-A16) plus the
Sprint 20 additions always import from source in CI.
"""

from __future__ import annotations

import importlib
import py_compile
from pathlib import Path

KEY_MODULES = [
    "evolver.experiment.trigger_shift",
    "evolver.experiment.cli",
    "evolver.cli_options",
    "evolver.gep.context_routing_gene",
    "evolver.gep.feedback_envelope",
    "evolver.gep.solidify_helpers",
    "evolver.gep.policy_check",
    "evolver.gep.validator.sandbox_executor",
    "evolver.proxy.asset_publish",
    "evolver.proxy.event_delivery",
]

# Standalone scripts (repo-root scripts/ dir, not a package): source presence
# + syntax check instead of import.
KEY_SCRIPTS = ["scripts/harness_governance_check.py"]


def test_key_modules_import_from_source() -> None:
    for module in KEY_MODULES:
        mod = importlib.import_module(module)
        source = getattr(mod, "__file__", "") or ""
        assert source.endswith(".py"), f"{module} imported from {source!r} — expected .py source"


def test_key_scripts_compile_from_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for rel in KEY_SCRIPTS:
        path = repo_root / rel
        assert path.is_file(), f"script source missing: {rel}"
        py_compile.compile(str(path), doraise=True)
