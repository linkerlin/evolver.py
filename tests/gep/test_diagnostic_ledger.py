"""Tests for evolver.gep.diagnostic_ledger (P2-7, round-74)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import diagnostic_ledger as dl
from evolver.gep.diagnostic_ledger import (
    backfill_attribution,
    find_similar,
    open_entry,
    symptom_signature,
)


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl, "ledger_path", lambda: tmp_path / "diagnostic_ledger.jsonl")


class TestSymptomSignature:
    def test_stable_across_calls(self) -> None:
        text = (
            "FAILED tests/test_x.py::test_y - assert 1 == 2\n"
            "=== short test summary ===\n3 failed, 3600 passed"
        )
        assert symptom_signature(text) == symptom_signature(text)

    def test_different_defects_different_sigs(self) -> None:
        a = symptom_signature("TypeError: cannot unpack non-iterable NoneType")
        b = symptom_signature("KeyError: 'hub_response'")
        assert a != b

    def test_empty_text_empty_sig(self) -> None:
        assert symptom_signature("") == ""


class TestOpenEntry:
    def test_opens_with_signature_and_components(self) -> None:
        entry = open_entry(
            run_id="run_1",
            event_id="evt_1",
            symptom_text="FAILED tests/test_x.py - assert False\n3 failed in 5.00s",
            suspect_components=["src/evolver/gep/solidify.py"],
        )
        assert entry is not None
        assert entry["type"] == "DiagnosticEntry"
        assert entry["suspect_components"] == ["src/evolver/gep/solidify.py"]
        assert entry["resolved"] is False
        stored = dl._load_entries(dl.ledger_path())
        assert stored and stored[0]["signature"] == entry["signature"]

    def test_recurrence_increments_not_duplicates(self) -> None:
        first = open_entry(
            run_id="run_1",
            event_id="evt_1",
            symptom_text="FAILED tests/x.py - KeyError: 'resp'\n2 failed in 1.00s",
            suspect_components=["a.py"],
        )
        second = open_entry(
            run_id="run_2",
            event_id="evt_2",
            symptom_text="FAILED tests/x.py - KeyError: 'resp'\n2 failed in 1.20s",
            suspect_components=["a.py"],
        )
        assert first is not None and second is not None
        assert second["recurrence"] == 1, "same-defect recurrence updates in place"


class TestBackfill:
    def test_backfill_marks_resolved(self, tmp_path: Path) -> None:
        entry = open_entry(
            run_id="run_1",
            event_id="evt_1",
            symptom_text="FAILED tests/x.py - assert False",
            suspect_components=["a.py"],
        )
        assert entry is not None
        row = backfill_attribution(
            entry["signature"],
            hypothesis="target lookup raced the rename",
            blamed_component="src/evolver/gep/rename.py",
        )
        assert row is not None and row["resolved"] is True
        assert row["blamed_component"] == "src/evolver/gep/rename.py"

    def test_backfill_unknown_signature_none(self) -> None:
        assert backfill_attribution("nope", hypothesis="h", blamed_component="c") is None


class TestFindSimilar:
    def test_retrieves_prior_attribution(self, tmp_path: Path) -> None:
        entry = open_entry(
            run_id="run_1",
            event_id="evt_1",
            symptom_text="FAILED tests/x.py - KeyError: 'resp'",
            suspect_components=["a.py"],
        )
        assert entry is not None
        similar = find_similar("FAILED tests/x.py - KeyError: 'resp'")
        assert similar and similar[0]["signature"] == entry["signature"]

    def test_disjoint_symptoms_not_retrieved(self, tmp_path: Path) -> None:
        open_entry(
            run_id="run_1",
            event_id="evt_1",
            symptom_text="FAILED tests/x.py - KeyError: 'resp'",
            suspect_components=["a.py"],
        )
        assert find_similar("Segmentation fault (core dumped)") == []
