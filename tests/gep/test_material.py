"""Sprint 24.8: material substrate — watermark ingest + consumer groups."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from evolver.gep.material import (
    BATCH_CAP,
    commit,
    consume,
    ingest_file,
    read_records,
)


@pytest.fixture
def log_file(temp_workspace: Path) -> Path:
    path = temp_workspace / "session.log"
    path.write_text("line-1\nline-2\nERROR: boom\n", encoding="utf-8")
    return path


def _touch(path: Path) -> None:
    os.utime(path, ns=(time.time_ns(), time.time_ns()))


class TestWatermarkIngest:
    def test_fresh_ingest_emits_all(self, log_file: Path) -> None:
        summary = ingest_file(log_file)
        assert summary["mode"] == "full"
        assert summary["added"] == 3
        texts = [r["text"] for r in read_records()]
        assert "ERROR: boom" in texts

    def test_unchanged_file_skipped(self, log_file: Path) -> None:
        ingest_file(log_file)
        summary = ingest_file(log_file)
        assert summary == {"source": str(log_file), "added": 0, "mode": "skipped"}
        assert len(read_records()) == 3

    def test_append_only_growth_emits_delta(self, log_file: Path) -> None:
        ingest_file(log_file)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("line-3\nWARN: tail\n")
        summary = ingest_file(log_file)
        assert summary["mode"] == "delta"
        assert summary["added"] == 2
        texts = [r["text"] for r in read_records()]
        assert "line-1" in texts and "line-3" in texts

    def test_identical_rewrite_is_noop(self, log_file: Path) -> None:
        content = log_file.read_text(encoding="utf-8")
        ingest_file(log_file)
        # Rewrite identical bytes (mtime changes → not the fast-skip path).
        _touch(log_file)
        log_file.write_text(content, encoding="utf-8")
        summary = ingest_file(log_file)
        assert summary["mode"] == "rewrite_noop"
        assert summary["added"] == 0
        assert len(read_records()) == 3

    def test_changed_rewrite_reingests(self, log_file: Path) -> None:
        ingest_file(log_file)
        _touch(log_file)
        log_file.write_text("brand-a\nbrand-b\n", encoding="utf-8")
        summary = ingest_file(log_file)
        assert summary["mode"] == "full"
        assert summary["added"] == 2

    def test_missing_source(self, temp_workspace: Path) -> None:
        summary = ingest_file(temp_workspace / "nope.log")
        assert summary["mode"] == "missing"

    def test_consecutive_duplicates_collapsed(self, temp_workspace: Path) -> None:
        path = temp_workspace / "dup.log"
        path.write_text("same\nsame\nsame\ndiff\n", encoding="utf-8")
        summary = ingest_file(path)
        assert summary["added"] == 2

    def test_batch_cap_enforced(self, temp_workspace: Path) -> None:
        path = temp_workspace / "big.log"
        path.write_text(
            "".join(f"row-{i} padding padding\n" for i in range(BATCH_CAP + 50)),
            encoding="utf-8",
        )
        summary = ingest_file(path)
        assert summary["added"] <= BATCH_CAP


class TestConsumerGroups:
    def test_at_least_once_until_commit(self, log_file: Path) -> None:
        ingest_file(log_file)
        first = consume("cycle")
        second = consume("cycle")
        assert [r["id"] for r in first] == [r["id"] for r in second]

        commit("cycle", first[-1]["id"])
        assert consume("cycle") == []

    def test_commit_advances_then_new_data_flows(self, log_file: Path) -> None:
        ingest_file(log_file)
        batch1 = consume("cycle", limit=1)
        commit("cycle", batch1[0]["id"])

        rest = consume("cycle")
        assert len(rest) == 2
        assert batch1[0]["id"] not in {r["id"] for r in rest}

    def test_unknown_group_starts_from_zero(self, log_file: Path) -> None:
        ingest_file(log_file)
        consume("cycle")
        commit("cycle", read_records()[-1]["id"])
        assert len(consume("fresh-group")) == 3


class TestCollectWiring:
    async def test_collect_phase_ingests_when_flag_on(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.asset_store import read_all_events
        from evolver.gep.feature_flags import invalidate_cache, set_flag

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        repo = temp_workspace
        (repo / "memory").mkdir(exist_ok=True)
        (repo / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
        log = repo / "memory" / "evolution" / "pipeline_events.jsonl"
        log.write_text("hello\nERROR: x\n", encoding="utf-8")

        set_flag("enable_material_ingest", True)
        invalidate_cache()
        try:
            from evolver.evolve.pipeline.collect import collect_phase

            ctx = await collect_phase({})
            assert ctx["material_ingest"]["added"] == 2
            types = [e["type"] for e in read_all_events()]
            assert "material_batch_ready" in types

            # Second run: unchanged → no new batch event.
            ctx = await collect_phase({})
            assert ctx["material_ingest"]["added"] == 0
        finally:
            set_flag("enable_material_ingest", False)
            invalidate_cache()

    async def test_collect_phase_noop_when_flag_off(self, temp_workspace: Path) -> None:
        from evolver.evolve.pipeline.collect import collect_phase

        ctx = await collect_phase({})
        assert "material_ingest" not in ctx


def test_records_survive_as_jsonl(temp_workspace: Path, log_file: Path) -> None:
    ingest_file(log_file)
    raw = (temp_workspace / "memory" / "evolution" / "material" / "material.jsonl").read_text(
        encoding="utf-8"
    )
    lines = [json.loads(x) for x in raw.splitlines() if x.strip()]
    assert len(lines) == 3
    assert {"id", "source", "kind", "content_hash", "text", "ts"} <= set(lines[0])
