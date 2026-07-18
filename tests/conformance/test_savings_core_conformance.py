"""savings-core CONFORMANCE test.

Ports Node's ``savingsCoreConformance.test.js``.  Two locks, same pattern as
every other savings-core consumer (evomap-hub, evomap-private, Node evolver):

1. impl == local copy — ``evolver.gep.savings_core`` must replay every
   vendored golden vector bit-for-bit, and its constants must equal the
   vendored ``constants.json``.
2. local copy == upstream — EvoMap/savings-core's drift-check compares the
   vendored files against the source of truth.

Additionally replays the E3 vectors through the REAL production path
(``token_savings.estimate_reuse_tokens_saved``) so the wrapper can never
drift from the spec formula it claims to implement.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from evolver.gep import savings_core as core
from evolver.gep.token_savings import estimate_reuse_tokens_saved

CONSTANTS: dict[str, Any] = json.loads(core.constants_path().read_text(encoding="utf-8"))
GOLDEN: dict[str, Any] = json.loads(core.golden_vectors_path().read_text(encoding="utf-8"))

_RUN = {
    "measured_savings": lambda i: core.measured_savings(i["raw_tokens"], i["optimized_tokens"]),
    "rollout_fold": lambda i: {"rollout_fold_pct": core.rollout_fold_pct(i["n_avg_rollouts"])},
    "entropy_total": lambda i: core.entropy_total(i["events"]),
    "fetch_usage_estimate": lambda i: {
        "estimated_token_saved": core.fetch_usage_estimate(i["byType"])
    },
    "reuse_estimate": lambda i: core.reuse_estimate(i["blast_radius_lines"], i["mode"]),
    "hit_rate": lambda i: {"hit_rate_pct": core.hit_rate_pct(i["hits"], i["misses"])},
    "usd_saved": lambda i: {"usd_saved": core.usd_saved(i["tokens"])},
    "cache_saved_usd": lambda i: {
        "cache_saved_usd": core.cache_saved_usd(i["provider"], i["cache_read_tokens"])
    },
}


def test_declares_the_same_spec_version_everywhere() -> None:
    assert CONSTANTS["spec_version"] == core.SAVINGS_SPEC_VERSION
    assert GOLDEN["spec_version"] == core.SAVINGS_SPEC_VERSION


def test_impl_constants_are_the_vendored_constants_json() -> None:
    assert core.CONSTANTS == CONSTANTS


def test_ships_the_full_vector_set_with_unique_ids() -> None:
    assert len(GOLDEN["cases"]) >= 25
    ids = [case["id"] for case in GOLDEN["cases"]]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: str(case["id"]))
def test_vector(case: dict[str, Any]) -> None:
    formula = case["formula"]
    assert formula in _RUN, f"unknown formula {formula} -- spec drifted ahead of impl"
    assert _RUN[formula](case["input"]) == case["expected"]


@pytest.mark.parametrize(
    "case",
    [case for case in GOLDEN["cases"] if case["formula"] == "reuse_estimate"],
    ids=lambda case: str(case["id"]),
)
def test_production_path(case: dict[str, Any]) -> None:
    lines = case["input"]["blast_radius_lines"]
    asset = None if lines is None else {"blast_radius": {"lines": lines}}
    assert estimate_reuse_tokens_saved(asset, case["input"]["mode"]) == case["expected"]
