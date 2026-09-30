"""`__all__` sanity — manually maintained export lists rot silently.

Round-98 (external review M5, minimal solution): a typo or a deleted symbol
in a hand-maintained `__all__` only surfaces at the first `from x import *`.
One pin per big export surface: every name must exist on its module.
"""

from __future__ import annotations

import importlib

import pytest

SURFACES = [
    "evolver.config",
    # asset_store deliberately absent: it maintains no __all__ at all (wild
    # import takes everything); forcing a hand-list here is churn, not safety.
    "evolver.gep.library",
    "evolver.gep.hypothesis",
    "evolver.gep.cursor",
    "evolver.bench.scoring",
    "evolver.bench.tasks",
    "evolver.bench.prompts",
]


@pytest.mark.parametrize("module_name", SURFACES)
def test_every_exported_name_exists(module_name: str) -> None:
    module = importlib.import_module(module_name)
    exported = getattr(module, "__all__", [])
    assert exported, f"{module_name} has no __all__"
    missing = [name for name in exported if not hasattr(module, name)]
    assert not missing, f"{module_name}.__all__ names missing on the module: {missing}"
