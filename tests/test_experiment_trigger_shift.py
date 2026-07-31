"""Offline trigger-shift replay evaluator tests.

Port of ``evolver/test/triggerShift.test.js`` (v1.93.0).
"""

from __future__ import annotations

import json
from typing import Any

from evolver.experiment import (
    TRIGGER_SHIFT_AXES,
    evaluate_trigger_shift,
    small_trigger_shift_suite,
)
from evolver.experiment import trigger_shift as ts

PAIR: dict[str, Any] = {
    "id": "wrapper-timeout-retry",
    "objectiveId": "safe-timeout-retry",
    "axis": "wrapper_trigger",
    "expectedDecision": "repair_timeout_source",
    "train": {
        "id": "train-wrapper-timeout-retry",
        "prompt": (
            "EVOLVER_TRIGGER: timeout retry loop. Fix the timeout source "
            "instead of adding more retries."
        ),
        "wrapperTrigger": "EVOLVER_TRIGGER",
    },
    "shifted": {
        "id": "shifted-wrapper-timeout-retry",
        "prompt": (
            "A service keeps retrying after timeouts. Fix the timeout "
            "source instead of adding more retries."
        ),
    },
}


class _StablePolicy:
    id = "stable-policy"

    def predict(self, task: Any) -> dict[str, Any]:
        return {"label": "repair_timeout_source"}


def _has_train_marker(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    return task.get("wrapperTrigger") == "EVOLVER_TRIGGER" or "EVOLVER_TRIGGER" in str(
        task.get("prompt") or ""
    )


class _TriggerSensitivePolicy:
    id = "trigger-sensitive-dummy"

    def predict(self, task: Any) -> dict[str, Any]:
        label = "repair_timeout_source" if _has_train_marker(task) else "add_more_retries"
        return {"label": label}


def test_empty_suite_zeroed_report() -> None:
    report = evaluate_trigger_shift(_StablePolicy(), [])
    assert report["policyId"] == "stable-policy"
    assert report["pairs"] == 0
    assert report["meanTrainReward"] == 0
    assert report["meanShiftedReward"] == 0
    assert report["meanGap"] == 0
    assert report["maxGap"] == 0
    assert report["rows"] == []


def test_stable_policy_aligned_rewards() -> None:
    report = evaluate_trigger_shift(_StablePolicy(), [PAIR])
    assert report["rows"][0]["trainReward"] == 1
    assert report["rows"][0]["shiftedReward"] == 1
    assert report["rows"][0]["gap"] == 0
    assert report["meanTrainReward"] == 1
    assert report["meanShiftedReward"] == 1
    assert report["meanGap"] == 0


def test_trigger_sensitive_policy_caught() -> None:
    report = evaluate_trigger_shift(_TriggerSensitivePolicy(), [PAIR])
    assert report["rows"][0]["trainDecision"] == "repair_timeout_source"
    assert report["rows"][0]["shiftedDecision"] == "add_more_retries"
    assert report["rows"][0]["trainReward"] == 1
    assert report["rows"][0]["shiftedReward"] == 0
    assert report["rows"][0]["gap"] == 1
    assert report["maxGap"] == 1
    assert report["meanGap"] == 1


def test_small_suite_covers_all_axes() -> None:
    axes = {p["axis"] for p in small_trigger_shift_suite()}
    assert axes == set(TRIGGER_SHIFT_AXES)
    assert axes == {"wrapper_trigger", "temporal_context", "instruction_phrasing"}


def test_report_omits_raw_prompt_metadata() -> None:
    encoded = json.dumps(evaluate_trigger_shift(_TriggerSensitivePolicy(), [PAIR]))
    assert "trainReward" in encoded
    assert "shiftedReward" in encoded
    assert "gap" in encoded
    assert "metadata" not in encoded
    assert "EVOLVER_TRIGGER: timeout retry loop" not in encoded


def test_unknown_axis_defaults_to_wrapper_trigger() -> None:
    pair = {**PAIR, "axis": "not_a_real_axis"}
    report = evaluate_trigger_shift(_StablePolicy(), [pair])
    assert report["rows"][0]["axis"] == "wrapper_trigger"


def test_none_policy_predicts_empty_label() -> None:
    report = evaluate_trigger_shift(None, [PAIR])
    assert report["policyId"] == "unknown"
    assert report["rows"][0]["trainDecision"] == ""
    assert report["rows"][0]["shiftedDecision"] == ""
    assert report["rows"][0]["trainReward"] == 0


def test_method_version_present() -> None:
    report = evaluate_trigger_shift(_StablePolicy(), [PAIR])
    assert report["methodVersion"] == "trigger-shift-v1"
    assert report["methodVersion"] == ts.TRIGGER_SHIFT_METHOD_VERSION


def test_package_exports() -> None:
    assert callable(evaluate_trigger_shift)
    assert callable(small_trigger_shift_suite)
    assert "wrapper_trigger" in TRIGGER_SHIFT_AXES
