"""Paired-session acceptance surface (演进方案.md §5.2 + §5.3).

Three claims are pinned here:

1. **Only a strict improvement publishes.** Drop, flat, unmeasured, an absent
   pack, a damaged gate, and a voided baseline all reject — and a reject never
   moves the baseline. This replaces round-79's "flat or up passes" plus its
   "unusable pack degrades to inactive", which together let a candidate that
   merely retuned the measuring instrument ship.
2. **A small val split needs two independent solves**, both beating the Parent.
   One lucky run is not reproducibility.
3. **No hypothesis, no gate.** A round without a record — or whose mechanism
   check cites val ids — is refused *before* the val gate runs.

Everything runs against a two-task synthetic pack with exact graders, so there
is no subprocess and no wall-clock dependency.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate
from evolver.gep import hypothesis as hypothesis_mod
from evolver.gep import val_seal

# ---------------------------------------------------------------------------
# Environment + synthetic pack
# ---------------------------------------------------------------------------


@pytest.fixture
def gate_env(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated home; nothing here touches the developer's real soak root."""
    home = temp_workspace / ".evomap-home"
    gep = temp_workspace / ".evolver" / "gep"
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return temp_workspace


def _synthetic_pack() -> dict[str, Any]:
    """Two val tasks plus one train task.

    The train task deliberately shares nothing but its existence with the val
    ones — any shared wording would become public material and drop out of the
    sealed set, which would mask exactly what these tests are checking.
    """
    val: dict[str, Any] = {
        "id": "probe-{n}",
        "split": "val",
        "title": "probe task {n}",
        "prompt": "Write the answer to answer.txt per brief.txt.",
        "sandbox": {"brief.txt": "Write exactly: ok\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": "ok"},
    }
    train: dict[str, Any] = {
        "id": "probe-train-1",
        "split": "train",
        "title": "train warmup",
        "prompt": "Read the warmup note and record its verdict.",
        "sandbox": {"note.txt": "warmup body\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": "yes"},
    }
    return {
        "pack_version": 1,
        "tasks": [
            {**val, "id": "probe-1", "title": "probe task 1"},
            {**val, "id": "probe-2", "title": "probe task 2"},
            train,
        ],
    }


def _freeze(gate_env: Path) -> Path:
    _ = gate_env
    path = frozen_gate.frozen_pack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_synthetic_pack(), indent=2), encoding="utf-8")
    return path


def _solve(replicate: int, answers: dict[str, str]) -> None:
    """Write the host's answers for one independent solve slot."""
    root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
    for task_id, answer in answers.items():
        sandbox = root / task_id
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "answer.txt").write_text(answer, encoding="utf-8")


def _all_correct() -> dict[str, str]:
    return {"probe-1": "ok", "probe-2": "ok"}


def _one_wrong() -> dict[str, str]:
    return {"probe-1": "wrong", "probe-2": "ok"}


def _establish_baseline() -> dict[str, Any]:
    """Set a Parent bar of 0.5 via the separate, mutation-free entry point."""
    _solve(1, _one_wrong())
    _solve(2, _one_wrong())
    report = frozen_gate.establish_parent_baseline()
    assert report["ok"] is True and report["score"] == 0.5, report
    return report


# ---------------------------------------------------------------------------
# 1. Only a strict improvement publishes
# ---------------------------------------------------------------------------


class TestStrictImprovementOnly:
    def test_armed_run_without_a_baseline_rejects_and_writes_nothing(self, gate_env: Path) -> None:
        """Before any Accept there is no bar — and a measurement must never
        write its own result into it.

        Two death traps in the old behaviour (first armed run saved the
        candidate's score as the bar): a strong first candidate raised the
        bar to itself, so the very same improvement became ``flat`` and could
        never be accepted; a weak one sank the bar below Parent, so a later
        regression read as a "strict improvement". The Parent bar comes from
        the separate, mutation-free measurement instead.
        """
        _freeze(gate_env)
        _solve(1, _all_correct())
        _solve(2, _all_correct())
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "no_baseline"
        assert verdict["accept"] is False
        assert verdict["score"] == 1.0
        assert frozen_gate.load_baseline() is None, "no Accept yet, so nothing may sit on the bar"

    def test_parent_baseline_is_written_only_by_the_separate_entry(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _solve(1, _one_wrong())
        _solve(2, _one_wrong())
        report = frozen_gate.establish_parent_baseline()
        assert report["ok"] is True and report["reason"] == "parent_baseline_written"
        assert report["score"] == 0.5
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_strict_improvement_accepts(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _all_correct())
        _solve(2, _all_correct())
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "accept"
        assert verdict["accept"] is True
        assert verdict["reason"] == "strict_improvement"
        assert verdict["scores"] == [1.0, 1.0]

    def test_flat_rejects_and_never_moves_the_baseline(self, gate_env: Path) -> None:
        """The round-79 rule was 'flat or up passes'. Flat now loses."""
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _one_wrong())
        _solve(2, _one_wrong())
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "flat"
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_drop_rejects_and_keeps_baseline(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, {"probe-1": "wrong", "probe-2": "wrong"})
        _solve(2, {"probe-1": "wrong", "probe-2": "wrong"})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "drop"
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_accept_advances_the_baseline(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _all_correct())
        _solve(2, _all_correct())
        frozen_gate.gate_verdict()
        assert frozen_gate.load_baseline()["score"] == 1.0


class TestUnmeasuredAndTrouble:
    def test_absent_pack_rejects(self, gate_env: Path) -> None:
        """No exam means no score, and no score means no publish.

        round-79 called this 'gate inactive' and let the mutation through.
        """
        _ = gate_env
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["accept"] is False
        assert verdict["reason"] == "pack_absent"

    def test_invalid_pack_rejects(self, gate_env: Path) -> None:
        path = _freeze(gate_env)
        path.write_text("{ not json", encoding="utf-8")
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "pack_absent"

    def test_unsolved_val_rejects_as_unmeasured(self, gate_env: Path) -> None:
        _freeze(gate_env)
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "unmeasured"
        assert verdict["scores"] == [None, None]

    def test_half_solved_replicates_reject(self, gate_env: Path) -> None:
        """One unsolved replicate withholds everything, not just that round."""
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _all_correct())
        shutil.rmtree(frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=2))
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "unmeasured"
        assert verdict["scores"][0] == 1.0 and verdict["scores"][1] is None
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_rekeyed_pack_voids_the_old_bar_without_publishing(self, gate_env: Path) -> None:
        path = _freeze(gate_env)
        _establish_baseline()
        old_digest = frozen_gate.load_baseline()["pack_digest"]
        payload = _synthetic_pack()
        payload["tasks"][1]["title"] = "changed rules"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _solve(1, _all_correct())
        _solve(2, _all_correct())
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "rekeyed_void"
        # The voided bar stays on disk bound to the OLD rules; the candidate
        # must not re-key it to its own score.
        assert frozen_gate.load_baseline()["pack_digest"] == old_digest
        assert frozen_gate.load_baseline()["pack_digest"] != verdict["digest"]


# ---------------------------------------------------------------------------
# 2. Small packs need two independent solves
# ---------------------------------------------------------------------------


class TestIndependentReplicates:
    def test_small_pack_scores_two_slots(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _all_correct())
        _solve(2, _all_correct())
        verdict = frozen_gate.gate_verdict()
        assert verdict["replicates"] == 2
        assert verdict["rounds"][0]["replicate"] == 1
        assert verdict["rounds"][1]["replicate"] == 2

    def test_solves_are_independent_dirs(self, gate_env: Path) -> None:
        _freeze(gate_env)
        first = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=1)
        second = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=2)
        assert first != second
        assert first.name == "r1" and second.name == "r2"

    def test_one_replicate_missing_rejects(self, gate_env: Path) -> None:
        _freeze(gate_env)
        _establish_baseline()
        _solve(1, _all_correct())
        _solve(2, _one_wrong())
        verdict = frozen_gate.gate_verdict()
        # slot 2 only matches the parent bar, so nothing is proven better
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "flat"
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_worst_replicate_decides(self, gate_env: Path) -> None:
        """A candidate is only as good as its weakest independent run."""
        _freeze(gate_env)
        verdict = frozen_gate.gate_verdict(require_replicate=True)
        assert verdict["replicates"] == 2
        opt_out = frozen_gate.gate_verdict(require_replicate=False)
        assert opt_out["replicates"] == 1


# ---------------------------------------------------------------------------
# 3. Hypotheses gate the gate
# ---------------------------------------------------------------------------


def _observation(ref: Any) -> Any:
    """Turn a bare id into a replayed before/after observation (§5.3)."""
    if isinstance(ref, dict):
        return ref
    return {
        "id": ref,
        "before": "the train task's sandbox showed the old behaviour",
        "after": "replayed after the change — the deliverable differs",
    }


def _record(dimension: str = "content", refs: Any = ("probe-train-1",)) -> dict[str, Any]:
    return {
        "hypothesis": "the missing constraint lets ambiguous readings pass",
        "dimension": dimension,
        "mechanism_family": "spec-literal",
        "target_hook": "dispatch prompt section 2",
        "mechanism_check": [_observation(ref) for ref in refs],
    }


class TestHypothesis:
    def test_valid_train_only_record_passes(self, gate_env: Path) -> None:
        _freeze(gate_env)
        ok, reason, detail = hypothesis_mod.validate_for_gate(_record())
        assert ok is True and reason == ""
        assert detail["dimension_label"] == "内容"
        assert detail["ref_check"] == "train_only"

    @pytest.mark.parametrize("dimension", ["content", "tool", "schema"])
    def test_only_three_dimensions_accepted(self, gate_env: Path, dimension: str) -> None:
        _freeze(gate_env)
        ok, reason, _ = hypothesis_mod.validate_for_gate(_record(dimension=dimension))
        assert ok is True, reason

    def test_fourth_dimension_rejected(self, gate_env: Path) -> None:
        _freeze(gate_env)
        ok, reason, _ = hypothesis_mod.validate_for_gate(_record(dimension="vibes"))
        assert ok is False
        assert reason == hypothesis_mod.REASON_BAD_DIMENSION

    @pytest.mark.parametrize("field", ["hypothesis", "mechanism_family", "target_hook"])
    def test_required_fields_are_mandatory(self, gate_env: Path, field: str) -> None:
        _freeze(gate_env)
        payload = _record()
        payload[field] = ""
        ok, reason, _ = hypothesis_mod.validate_for_gate(payload)
        assert ok is False
        assert reason in {
            hypothesis_mod.REASON_EMPTY_HYPOTHESIS,
            hypothesis_mod.REASON_EMPTY_FAMILY,
            hypothesis_mod.REASON_EMPTY_TARGET,
        }

    def test_empty_mechanism_check_rejected(self, gate_env: Path) -> None:
        _freeze(gate_env)
        ok, reason, _ = hypothesis_mod.validate_for_gate(_record(refs=[]))
        assert ok is False
        assert reason == hypothesis_mod.REASON_MISSING_CHECK

    def test_missing_record_is_reported_as_missing(self, gate_env: Path) -> None:
        _freeze(gate_env)
        ok, reason, _ = hypothesis_mod.validate_for_gate(None)
        assert ok is False
        assert reason == hypothesis_mod.REASON_MISSING_RECORD

    def test_val_reference_rejected(self, gate_env: Path) -> None:
        """The whole point: a val id in the check means the seal is broken."""
        _freeze(gate_env)
        ok, reason, detail = hypothesis_mod.validate_for_gate(_record(refs=["probe-2"]))
        assert ok is False
        assert reason == hypothesis_mod.REASON_VAL_REF
        assert detail["val_refs"] == ["probe-2"]

    def test_unknown_reference_rejected(self, gate_env: Path) -> None:
        _freeze(gate_env)
        ok, reason, detail = hypothesis_mod.validate_for_gate(_record(refs=["nope-9"]))
        assert ok is False
        assert reason == hypothesis_mod.REASON_UNKNOWN_REF
        assert detail["unknown_refs"] == ["nope-9"]

    def test_dict_refs_supported(self, gate_env: Path) -> None:
        _freeze(gate_env)
        payload = _record(
            refs=[{"id": "probe-train-1", "before": 0.0, "after": 1.0}],
        )
        ok, _reason, detail = hypothesis_mod.validate_for_gate(payload)
        assert ok is True
        assert detail["refs"] == ["probe-train-1"]

    def test_unarmed_pack_defers_the_ref_check(self, gate_env: Path) -> None:
        """No pack means no train ids to check against — say so, don't pretend."""
        _ = gate_env
        ok, _reason, detail = hypothesis_mod.validate_for_gate(_record())
        assert ok is True
        assert detail["pack_armed"] is False
        assert detail["ref_check"] == "deferred_no_pack"

    def test_record_roundtrip(self, gate_env: Path) -> None:
        _freeze(gate_env)
        path = hypothesis_mod.record_hypothesis(_record())
        assert path.is_file()
        loaded = hypothesis_mod.load_hypothesis()
        assert loaded is not None
        assert loaded["dimension"] == "content"
        hypothesis_mod.clear_hypothesis()
        assert hypothesis_mod.load_hypothesis() is None

    def test_record_hypothesis_refuses_garbage(self, gate_env: Path) -> None:
        _freeze(gate_env)
        with pytest.raises(hypothesis_mod.HypothesisError):
            hypothesis_mod.record_hypothesis({"dimension": "vibes"})


# ---------------------------------------------------------------------------
# 4. Sealed val secrets
# ---------------------------------------------------------------------------


class TestValSeal:
    def test_secrets_exclude_material_shared_with_train(self, gate_env: Path) -> None:
        """Public material is not a secret — otherwise every train mention trips."""
        _freeze(gate_env)
        secrets = val_seal.sealed_secrets()
        values = {str(entry["value"]) for entry in secrets}
        assert "Write the answer to answer.txt per brief.txt." in values
        assert "probe task 1" in values

    def test_shared_fixture_body_is_not_a_secret(self, gate_env: Path) -> None:
        """A val task and a train task sharing one fixture does not make the
        fixture secret — only the val-specific parts stay sealed."""
        path = _freeze(gate_env)
        payload = json.loads(path.read_text(encoding="utf-8"))
        fixture = "shared fixture body\n"
        payload["tasks"].append(
            {
                "id": "probe-train-2",
                "split": "train",
                "title": "train task",
                "prompt": "Read shared.txt and summarise.",
                "sandbox": {"shared.txt": fixture},
                "grader": {"type": "exact", "file": "out.txt", "expected": "yes"},
            }
        )
        payload["tasks"][0]["sandbox"]["shared.txt"] = fixture
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        secrets = {str(entry["value"]) for entry in val_seal.sealed_secrets()}
        assert fixture.strip() not in secrets

    def test_short_answers_are_weak_not_strong(self, gate_env: Path) -> None:
        _freeze(gate_env)
        secrets = val_seal.sealed_secrets()
        ok_entry = next(entry for entry in secrets if entry["value"] == "ok")
        assert ok_entry["signal"] == "weak"

    def test_plain_text_has_no_secrets(self, gate_env: Path) -> None:
        _freeze(gate_env)
        assert val_seal.strong_scan("improve the prompt in dispatch") == []

    def test_assert_sealed_raises_on_leak(self, gate_env: Path) -> None:
        _freeze(gate_env)
        secrets = val_seal.sealed_secrets()
        strong = next(e for e in secrets if e["signal"] == "strong")
        with pytest.raises(val_seal.ValSealBreachError, match="val seal breached"):
            val_seal.assert_sealed(f"hint: {strong['value']}", where="dispatch")

    def test_weak_alone_does_not_raise(self, gate_env: Path) -> None:
        """'ok' is two letters; it must not fail every ordinary sentence."""
        _freeze(gate_env)
        val_seal.assert_sealed("the result was ok", where="dispatch")

    def test_redact_replaces_and_counts(self, gate_env: Path) -> None:
        _freeze(gate_env)
        secrets = val_seal.sealed_secrets()
        strong = next(e for e in secrets if e["signal"] == "strong")
        scrubbed, report = val_seal.redact(f"task says {strong['value']}", where="dispatch")
        assert strong["value"] not in scrubbed
        assert val_seal.REDACTION_PLACEHOLDER in scrubbed
        assert report["redacted"] == 1

    def test_unarmed_pack_claims_nothing(self, gate_env: Path) -> None:
        _ = gate_env
        assert val_seal.sealed_secrets() == []
        assert val_seal.task_ids()["val"] == []
        assert val_seal.seal_report("anything", where="dispatch")["armed"] is False
