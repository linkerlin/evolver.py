"""Tests for evolver.gep.variant_archive (RSI P1-3, round-40)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.gep.variant_archive import (
    classify_rejection,
    load_variants,
    re_dispatchable_variants,
    record_variant,
    variant_entry,
)


def _failed_event(
    *, diff: str = "diff --git a/x b/x\n+fix\n", gene: str = "gene_a"
) -> dict[str, Any]:
    return {
        "id": "evt_v1",
        "run_id": "run_v1",
        "gene_id": gene,
        "timestamp": "2026-09-20T00:00:00Z",
        "signals": ["log_error", "autopoiesis:auto_friction"],
        "outcome": {"status": "failed", "error": "validation_failed", "score": 0.9},
        "diff_snapshot": diff,
    }


class TestClassifyRejection:
    def test_timeout_is_environmental(self) -> None:
        vr = {
            "results": [
                {"command": "pytest", "ok": False, "stderr": "Command timed out after 600s"}
            ]
        }
        assert classify_rejection(vr) == "environmental"

    def test_oserror_is_environmental(self) -> None:
        vr = {
            "commands": [
                {"command": "pytest", "ok": False, "stderr": "OSError: [Errno 2] No such file"}
            ]
        }
        assert classify_rejection(vr) == "environmental"

    def test_assertion_is_semantic(self) -> None:
        vr = {"results": [{"command": "pytest", "ok": False, "stdout": "3 failed, 3649 passed"}]}
        assert classify_rejection(vr) == "semantic"

    def test_no_failed_stage_or_no_validation(self) -> None:
        assert classify_rejection(None) is None
        assert classify_rejection({"results": [{"command": "ruff", "ok": True}]}) is None


class TestVariantEntry:
    def test_entry_shape_with_replay(self) -> None:
        entry = variant_entry(_failed_event(), "environmental")
        assert entry is not None
        assert entry["type"] == "VariantArchiveEntry"
        assert entry["gene_id"] == "gene_a"
        assert entry["signal_heads"] == ["autopoiesis", "log_error"]
        assert entry["rejection_class"] == "environmental"
        assert entry["replay"]["kind"] == "unified_diff"
        assert "+fix" in entry["replay"]["diff"]

    def test_entry_without_edit_skipped(self) -> None:
        ev = _failed_event(diff="")
        ev.pop("diff_snapshot")
        assert variant_entry(ev, "semantic") is None


class TestRecordAndLoad:
    def test_record_then_load_roundtrip(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
        entry = record_variant(_failed_event(), "environmental")
        assert entry is not None
        path = tmp_path / "candidates.jsonl"
        raw = json.loads(path.read_text(encoding="utf-8").strip())
        assert raw["variant_id"] == entry["variant_id"]
        loaded = load_variants(path)
        assert len(loaded) == 1
        assert loaded[0]["rejection_class"] == "environmental"

    def test_load_skips_malformed_and_foreign_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "candidates.jsonl"
        path.write_text(
            "not-json\n"
            '{"type": "SomethingElse", "id": "x"}\n'
            + json.dumps(variant_entry(_failed_event(), "semantic") or {})
            + "\n",
            encoding="utf-8",
        )
        assert len(load_variants(path)) == 1


class TestReDispatchable:
    def _entry(self, cls: str, heads: list[str], fp_diff: str) -> dict[str, Any]:
        ev = _failed_event(diff=fp_diff)
        e = variant_entry(ev, cls) or {}
        e["signal_heads"] = heads
        return e

    def test_environmental_family_match_eligible(self) -> None:
        entries = [self._entry("environmental", ["log_error"], "diff --git a/p b/p\n+env\n")]
        out = re_dispatchable_variants(entries, ["log_error", "hub_offline"], [])
        assert len(out) == 1

    def test_semantic_rejection_not_eligible(self) -> None:
        entries = [self._entry("semantic", ["log_error"], "diff --git a/p b/p\n+sem\n")]
        assert re_dispatchable_variants(entries, ["log_error"], []) == []

    def test_family_mismatch_not_eligible(self) -> None:
        entries = [self._entry("environmental", ["hub_offline"], "diff --git a/p b/p\n+env\n")]
        assert re_dispatchable_variants(entries, ["log_error"], []) == []

    def test_superseded_fingerprint_not_eligible(self) -> None:
        diff = "diff --git a/p b/p\n+later-landed\n"
        entries = [self._entry("environmental", ["log_error"], diff)]
        success = {
            "id": "evt_ok",
            "outcome": {"status": "success"},
            "signals": ["log_error"],
            "diff_snapshot": diff,
        }
        assert re_dispatchable_variants(entries, ["log_error"], [success]) == []
