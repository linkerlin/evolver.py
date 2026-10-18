"""RERE is a report score. It does not enter the acceptance gate."""

from __future__ import annotations

from evolver.experiment.metrics import rere_score
from evolver.ops.meta_report import rere_panel


def test_square_penalty_and_cap() -> None:
    assert rere_score(accepted=True, rounds_used=1) == 1.15
    assert rere_score(accepted=True, rounds_used=2) == 1.0
    assert rere_score(accepted=True, rounds_used=4) == 0.25
    assert rere_score(accepted=True, rounds_used=4, r_ref=1) == 0.0625
    assert rere_score(accepted=False, rounds_used=1) == 0.0


def test_panel_averages_accepted_sessions_only() -> None:
    panel = rere_panel(
        [
            {"status": "accepted", "round": 1},
            {"status": "accepted", "round": 2},
            {"status": "incomplete", "round": 8},
        ]
    )
    assert panel["accepted_scored"] == 2
    assert panel["rere_score"] == 1.075
    assert rere_panel(None)["rere_score"] is None
