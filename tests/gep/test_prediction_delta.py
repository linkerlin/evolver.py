"""Engine-side prediction delta, not a host-supplied after-the-fact story."""

from __future__ import annotations

from pathlib import Path

from evolver.gep import episode_record
from evolver.gep.evidence import save_evidence
from evolver.gep.hypothesis import (
    compute_prediction_delta,
    consume_hypothesis,
    record_hypothesis,
)


def test_no_observed_checks_is_not_a_mismatch() -> None:
    delta = compute_prediction_delta({"expected_checks_to_pass": ["pytest"]}, [])
    assert delta["matched"] is None
    assert delta["unmet_expectations"] == []


def test_delta_marks_unmet_and_unexpected() -> None:
    delta = compute_prediction_delta(
        {
            "expected_checks_to_pass": ["pytest"],
            "expected_invariants": "cli help text stays",
        },
        [
            {"command": "uv run pytest", "ok": False},
            {"command": "uv run mypy", "ok": False},
        ],
    )
    assert delta["matched"] is False
    assert delta["unmet_expectations"] == ["pytest"]
    assert delta["unexpected_failures"] == ["uv run mypy"]
    assert delta["invariants_recorded"] is True
    assert delta["source"] == "engine"
    assert "cli help" not in str(delta)


def _save_delta_scene() -> None:
    scene = {
        "event": {
            "id": "evt_delta",
            "run_id": "run_delta",
            "timestamp": "2026-10-18T00:00:00.000Z",
            "gene_id": "gene_d",
            "mutation": {"id": "mut_d", "category": "repair"},
            "diff_snapshot": "+z\n",
            "outcome": {"status": "failed", "score": 0.0},
        },
        "validation_result": {
            "ok": False,
            "results": [{"command": "uv run pytest", "ok": True, "stdout": "ok", "stderr": ""}],
        },
        "gate": {"accepted": False},
    }
    save_evidence("run_delta", "evt_delta", scene)


def test_an_unconsumed_hypothesis_is_not_this_rounds_claim(temp_workspace: Path) -> None:
    record_hypothesis(
        {
            "hypothesis": "declared but never reached the gate",
            "dimension": "tool",
            "mechanism_family": "repair",
            "target_hook": "episode_record",
            "run_id": "run_delta",
            "mechanism_check": [{"id": "train-1", "before": "fail", "after": "pass"}],
            "expected_outcome": {"expected_checks_to_pass": ["pytest"]},
        }
    )
    _save_delta_scene()
    stored = episode_record.record_round(event_id="evt_delta", run_id="run_delta")
    body = episode_record.load_episode(stored["id"])
    assert body is not None
    assert "prediction_delta" not in body["gates"]


def test_record_round_writes_the_delta_from_the_hypothesis(temp_workspace: Path) -> None:
    record_hypothesis(
        {
            "hypothesis": "the clip hides the assertion",
            "dimension": "tool",
            "mechanism_family": "repair",
            "target_hook": "episode_record",
            "run_id": "run_delta",
            "mechanism_check": [{"id": "train-1", "before": "fail", "after": "pass"}],
            "expected_outcome": {"expected_checks_to_pass": ["pytest"]},
        }
    )
    consume_hypothesis("run_delta")
    _save_delta_scene()
    stored = episode_record.record_round(event_id="evt_delta", run_id="run_delta")
    body = episode_record.load_episode(stored["id"])
    assert body is not None
    delta = body["gates"]["prediction_delta"]
    assert delta["matched"] is True
    assert delta["unmet_expectations"] == []


def test_rendered_block_adds_the_delta_line_only_when_recorded() -> None:
    body = {
        "run_id": "run_r",
        "gene": {"id": "gene_r"},
        "outcome": {"status": "failed", "score": 0.0},
        "gates": {"acceptance": {"accepted": False}},
        "checks": [{"command": "uv run mypy", "ok": False}],
        "diff": "+z\n",
    }
    without = episode_record.render_episode_block(body, ep_id="ep_r")
    assert "prediction_delta" not in without

    with_delta = dict(body)
    with_delta["gates"] = {
        "acceptance": {"accepted": False},
        "prediction_delta": {
            "matched": False,
            "unmet_expectations": ["pytest"],
            "unexpected_failures": ["uv run mypy"],
        },
    }
    line = '- prediction_delta: matched=False unmet=["pytest"] unexpected=["uv run mypy"]'
    rendered = episode_record.render_episode_block(with_delta, ep_id="ep_r")
    assert line in rendered
    assert rendered.replace(line + "\n", "") == without


def test_bad_expected_outcome_is_refused() -> None:
    from evolver.gep.hypothesis import REASON_BAD_EXPECTED, validate_record

    ok, reason = validate_record(
        {
            "hypothesis": "x",
            "dimension": "tool",
            "mechanism_family": "repair",
            "target_hook": "t",
            "mechanism_check": [{"id": "train-1", "before": "a", "after": "b"}],
            "expected_outcome": {"expected_checks_to_pass": [1]},
        }
    )
    assert ok is False
    assert reason == REASON_BAD_EXPECTED
