"""The val seal (演进方案.md §5.2) — sealed strings never reach design context.

1:1 with ``evolver.gep.val_seal``. Two honesty rules pinned here: material a
train task also carries is public by construction; expected answers too short
to trust are reported weak but never decide a breach.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import val_seal


@pytest.fixture
def seal_env(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = temp_workspace / ".evomap-home"
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(temp_workspace / ".evolver" / "gep"))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return temp_workspace


def _arm_pack(tasks: list[dict[str, Any]]) -> None:
    from evolver.bench import frozen_gate

    path = frozen_gate.frozen_pack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pack_version": 1, "tasks": tasks}, indent=2), encoding="utf-8")


def _pack() -> list[dict[str, Any]]:
    """Train and val share one fixture string; val alone owns the rest."""
    shared_log = "ERROR disk full on /dev/sda1\nERROR net timeout host=queue.internal"
    return [
        {
            "id": "train-shared",
            "split": "train",
            "title": "shared fixture reader",
            "prompt": f"Extract from:\n{shared_log}",
            "sandbox": {"input.log": shared_log},
            "grader": {"type": "exact", "file": "out.txt", "expected": shared_log},
        },
        {
            "id": "val-a",
            "split": "val",
            "title": "the sealed question wording is long enough to be strong",
            "prompt": "Write the quarterly reconciliation breakdown by ledger id.",
            "sandbox": {"input.log": shared_log, "rules.txt": "UNIQUE-VAL-ONLY-RULESET-42"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "reconciled:42|ledger"},
        },
        {
            "id": "val-b",
            "split": "val",
            "title": "short answer task",
            "prompt": "Write the median of nums.txt.",
            "sandbox": {"nums.txt": "1\n2\n3"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "2"},
        },
    ]


def _arm(seal_env: Path) -> None:
    _arm_pack(_pack())


class TestUnarmedSeal:
    def test_no_pack_means_empty_id_buckets(self, seal_env: Path) -> None:
        assert val_seal.task_ids() == {"train": [], "val": []}

    def test_no_pack_means_no_secrets(self, seal_env: Path) -> None:
        assert val_seal.sealed_secrets() == []

    def test_unarmed_scan_and_assert_are_inert(self, seal_env: Path) -> None:
        assert val_seal.scan("anything at all") == []
        val_seal.assert_sealed("anything at all", where="test")  # must not raise
        report = val_seal.seal_report("anything", where="test")
        assert report["armed"] is False and report["hits"] == 0


class TestSecretExtraction:
    def test_ids_split_by_bucket(self, seal_env: Path) -> None:
        _arm(seal_env)
        assert val_seal.task_ids()["train"] == ["train-shared"]
        assert sorted(val_seal.task_ids()["val"]) == ["val-a", "val-b"]

    def test_shared_train_material_is_public_not_secret(self, seal_env: Path) -> None:
        _arm(seal_env)
        shared_log = "ERROR disk full on /dev/sda1\nERROR net timeout host=queue.internal"
        values = {str(e["value"]) for e in val_seal.sealed_secrets()}
        assert shared_log not in values  # the train task carries it too

    def test_val_only_strings_are_secrets(self, seal_env: Path) -> None:
        _arm(seal_env)
        values = {str(e["value"]) for e in val_seal.sealed_secrets()}
        assert "UNIQUE-VAL-ONLY-RULESET-42" in values  # sandbox body
        assert "Write the quarterly reconciliation breakdown by ledger id." in values

    def test_short_answers_are_weak_long_ones_strong(self, seal_env: Path) -> None:
        _arm(seal_env)
        by_value = {str(e["value"]): str(e["signal"]) for e in val_seal.sealed_secrets()}
        assert by_value["2"] == "weak"  # median — below MIN_SECRET_LEN
        assert by_value["reconciled:42|ledger"] == "strong"

    def test_secrets_are_unique_and_longest_first(self, seal_env: Path) -> None:
        _arm(seal_env)
        entries = val_seal.sealed_secrets()
        values = [str(e["value"]) for e in entries]
        assert len(values) == len(set(values))
        lengths = [len(v) for v in values]
        assert lengths == sorted(lengths, reverse=True)

    def test_non_string_expected_is_stringified(self, seal_env: Path) -> None:
        _arm_pack(
            [
                {
                    "id": "v",
                    "split": "val",
                    "title": "t",
                    "prompt": "p long enough to matter here",
                    "sandbox": {"in": "x"},
                    "grader": {"type": "json_field", "file": "o.json", "path": "r", "expected": 42},
                }
            ]
        )
        values = {str(e["value"]) for e in val_seal.sealed_secrets()}
        assert "42" in values  # json.dumps(42) == "42"


class TestScanAndAssert:
    def test_strong_hit_is_reported_by_scan(self, seal_env: Path) -> None:
        _arm(seal_env)
        hits = val_seal.scan("the answer is reconciled:42|ledger according to the draft")
        assert any(str(h["value"]) == "reconciled:42|ledger" for h in hits)

    def test_weak_hit_is_reported_but_never_decides(self, seal_env: Path) -> None:
        _arm(seal_env)
        # "2" appears everywhere in ordinary prose; the seal must not fire.
        val_seal.assert_sealed("chapter 2 covers the topic", where="test")

    def test_assert_sealed_raises_on_a_strong_hit(self, seal_env: Path) -> None:
        _arm(seal_env)
        with pytest.raises(val_seal.ValSealBreachError, match="val seal breached"):
            val_seal.assert_sealed(
                "design note: write reconciled:42|ledger to satisfy the grader",
                where="dispatch",
            )

    def test_shared_material_never_breaches(self, seal_env: Path) -> None:
        _arm(seal_env)
        shared_log = "ERROR disk full on /dev/sda1\nERROR net timeout host=queue.internal"
        val_seal.assert_sealed(f"context: {shared_log}", where="evidence_pack")


class TestRedact:
    def test_redact_replaces_strong_hits_and_counts_them(self, seal_env: Path) -> None:
        _arm(seal_env)
        text = "prefix reconciled:42|ledger suffix"
        scrubbed, report = val_seal.redact(text, where="dispatch")
        assert "reconciled:42|ledger" not in scrubbed
        assert val_seal.REDACTION_PLACEHOLDER in scrubbed
        assert "prefix" in scrubbed and "suffix" in scrubbed
        assert report["redacted"] == 1

    def test_redact_leaves_weak_strings_untouched(self, seal_env: Path) -> None:
        _arm(seal_env)
        scrubbed, _report = val_seal.redact("chapter 2 and section 2", where="dispatch")
        assert scrubbed == "chapter 2 and section 2"

    def test_redact_on_empty_text(self, seal_env: Path) -> None:
        scrubbed, report = val_seal.redact("", where="dispatch")
        assert scrubbed == ""
        assert report["redacted"] == 0

    def test_report_names_the_hit_sources(self, seal_env: Path) -> None:
        _arm(seal_env)
        # scan() reports weak hits too ("2" from val-b matches "42") — sources
        # is a superset; the strong verdict is what the seal acts on.
        report = val_seal.seal_report("contains reconciled:42|ledger", where="proposal")
        assert report["strong_hits"] == 1
        assert "val-a" in report["sources"]
