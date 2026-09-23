"""Tests for the solidify → diagnostic-ledger funnel (round-75, P2-7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evolver.gep.diagnostic_ledger import _load_entries, ledger_path
from evolver.gep.solidify import _append_failure_event


def _validation_result() -> dict[str, Any]:
    return {
        "results": [
            {"command": "ruff check src tests", "ok": True, "stdout": "ok"},
            {
                "command": "mypy src",
                "ok": False,
                "stderr": "src/x.py:1: error: Name 'y' is not defined",
            },
        ]
    }


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_diag",
        "signals": ["log_error"],
        "selected_gene_id": "gene_diag",
        "mutation": {"id": "m1", "validation": []},
    }


class TestDiagnosticFunnel:
    def test_failure_opens_ledger_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evo"))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
        (tmp_path / "gep").mkdir()
        monkeypatch.setattr("evolver.gep.feature_flags.is_enabled", lambda _: True)

        _append_failure_event(
            _last_run(),
            tmp_path,
            blast_radius={"files": 1},
            error="validation_failed",
            validation_result=_validation_result(),
        )
        entries = _load_entries(ledger_path())
        assert len(entries) == 1
        row = entries[0]
        assert row["run_id"] == "run_diag"
        assert "mypy" in row["suspect_components"]
        assert row["hypothesis"] == "", "attribution is host-backfilled later"

    def test_ledger_failure_never_breaks_event_flow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evo"))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
        (tmp_path / "gep").mkdir()
        # Corrupt the ledger path into a directory so the write fails.
        broken = tmp_path / "evo" / "diagnostic_ledger.jsonl"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.mkdir()
        monkeypatch.setattr("evolver.gep.feature_flags.is_enabled", lambda _: True)

        # Must NOT raise even though the ledger write path is broken.
        _append_failure_event(
            _last_run(),
            tmp_path,
            blast_radius={"files": 1},
            error="validation_failed",
            validation_result=_validation_result(),
        )
