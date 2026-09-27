"""Tests for evolver.bench.regression_guard (charter 配对会话 §5.2).

The aggregate gate sees only the mean, so a candidate can raise the mean
while collapsing one task. The floor list is what closes that hole: every
val task must not fall below the Parent's own score on that same task, and
the candidate may only ADD floors of its own.

A missing floor source is not a waiver — it is an unmeasured floor, and
unmeasured rejects.
"""

from __future__ import annotations

from evolver.bench import regression_guard


def _rounds(*per_round: list[dict]) -> list[list[dict]]:
    return list(per_round)


def _graded(**scores: float) -> list[dict]:
    return [{"id": key, "status": "graded", "score": value} for key, value in scores.items()]


BASELINE = {"score": 0.8, "per_task": {"a": 0.6, "b": 1.0}}


def test_baseline_without_per_task_is_a_refusal_not_a_waiver() -> None:
    verdict = regression_guard.assert_no_regression(
        _rounds(_graded(a=1.0, b=1.0)), baseline={"score": 0.8}
    )
    assert verdict["ok"] is False
    assert verdict["reason"] == regression_guard.REASON_NO_FLOOR_SOURCE


def test_floors_come_from_the_parents_own_scores() -> None:
    assert regression_guard.floors_from_baseline(BASELINE) == {"a": 0.6, "b": 1.0}


def test_a_non_finite_baseline_score_is_not_a_floor() -> None:
    assert regression_guard.floors_from_baseline({"per_task": {"a": float("nan")}}) is None
    assert regression_guard.floors_from_baseline({"per_task": {"a": float("inf")}}) is None


def test_absent_declaration_is_legal_and_adds_nothing() -> None:
    floors, reason = regression_guard.floors_from_declaration({"hypothesis": "x"})
    assert floors == {} and reason == ""


def test_malformed_declaration_is_refused() -> None:
    for bad in (
        {"no_regressions": "a"},
        {"no_regressions": [{"id": "a"}]},
        {"no_regressions": [{"floor": 1.0}]},
        {"no_regressions": ["a"]},
        {"no_regressions": [{"id": "a", "floor": float("nan")}]},
    ):
        floors, reason = regression_guard.floors_from_declaration(bad)
        assert floors == {} and reason == regression_guard.REASON_BAD_DECLARATION


def test_declaration_may_only_cite_train_ids() -> None:
    floors, reason = regression_guard.floors_from_declaration(
        {"no_regressions": [{"id": "secret-val", "floor": 1.0}]},
        task_ids={"train": ["train-1"], "val": ["secret-val"]},
    )
    assert floors == {} and reason == regression_guard.REASON_BAD_DECLARATION


def test_a_declared_floor_may_only_tighten_never_loosen() -> None:
    merged = regression_guard.merge_floors({"a": 0.6}, {"a": 0.2, "b": 0.9})
    assert merged == {"a": 0.6, "b": 0.9}


def test_no_regression_passes_when_every_task_holds() -> None:
    verdict = regression_guard.assert_no_regression(
        _rounds(_graded(a=0.6, b=1.0), _graded(a=0.9, b=1.0)), baseline=BASELINE
    )
    assert verdict["ok"] is True
    assert verdict["violations"] == []


def test_a_single_collapsed_task_rejects_even_when_the_mean_rises() -> None:
    # a rises from 0.6 to 1.0, b collapses from 1.0 to 0.0: the mean is flat
    # but the pack just lost a capability. The aggregate gate cannot see it.
    verdict = regression_guard.assert_no_regression(
        _rounds(_graded(a=1.0, b=0.0), _graded(a=1.0, b=1.0)), baseline=BASELINE
    )
    assert verdict["ok"] is False
    assert verdict["reason"] == regression_guard.REASON_REGRESSION
    assert [v["id"] for v in verdict["violations"]] == ["b"]


def test_every_replicate_is_checked_not_just_the_mean() -> None:
    verdict = regression_guard.assert_no_regression(
        _rounds(_graded(a=1.0, b=1.0), _graded(a=1.0, b=0.5)), baseline=BASELINE
    )
    assert verdict["ok"] is False
    assert verdict["violations"][0]["replicate"] == 2


def test_an_unmeasured_task_is_not_a_pass() -> None:
    rounds = _rounds(
        [{"id": "a", "status": "graded", "score": 1.0}, {"id": "b", "status": "pending"}]
    )
    verdict = regression_guard.assert_no_regression(rounds, baseline=BASELINE)
    assert verdict["ok"] is False
    assert verdict["reason"] == regression_guard.REASON_UNMEASURED_TASK
    assert verdict["unmeasured_tasks"] == ["b"]


def test_a_boolean_score_is_not_a_number() -> None:
    rounds = _rounds([{"id": "a", "status": "graded", "score": True}])
    verdict = regression_guard.assert_no_regression(rounds, baseline={"per_task": {"a": 0.6}})
    assert verdict["ok"] is False


def test_declared_floors_bind_in_addition_to_the_global_list() -> None:
    verdict = regression_guard.assert_no_regression(
        _rounds(_graded(a=1.0, b=1.0, train_1=0.5)),
        baseline=BASELINE,
        declaration={"no_regressions": [{"id": "train_1", "floor": 0.9}]},
        task_ids={"train": ["train_1"], "val": ["a", "b"]},
    )
    assert verdict["ok"] is False
    assert verdict["violations"][0]["id"] == "train_1"
    assert verdict["floors"]["train_1"] == 0.9


def test_reject_reasons_are_stable_strings() -> None:
    assert regression_guard.REASON_REGRESSION == "regression_below_floor"
    assert regression_guard.REASON_NO_FLOOR_SOURCE == "baseline_without_per_task"
