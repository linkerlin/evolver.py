"""Tests for evolver.gep.asset_call_log.

Ports the contract scenarios from Node's ``assetCallLog.test.js``, plus the
``reuseAttributionSummary``/``assetCostIndex`` rollups and the CLI fix that
makes ``evolver asset-log`` read asset_call_log.jsonl instead of events.jsonl.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evolver.cli import main
from evolver.gep.asset_call_log import (
    asset_cost_index,
    get_log_path,
    log_asset_call,
    read_call_log,
    reuse_attribution_summary,
    summarize_call_log,
)


@pytest.fixture(autouse=True)
def _isolated_evolution_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    evolution_dir = tmp_path / "evolution"
    monkeypatch.setenv("EVOLUTION_DIR", str(evolution_dir))
    return evolution_dir


class TestGetLogPath:
    def test_path_under_evolution_dir(self, _isolated_evolution_dir: Path) -> None:
        log_path = get_log_path()
        assert str(log_path).startswith(str(_isolated_evolution_dir))
        assert log_path.name == "asset_call_log.jsonl"


class TestLogAssetCall:
    def test_creates_log_file_on_first_write(self) -> None:
        assert not get_log_path().exists()
        log_asset_call({"run_id": "r1", "action": "asset_reuse", "asset_id": "a1"})
        assert get_log_path().exists()

    def test_appends_ndjson_record_with_timestamp(self) -> None:
        log_asset_call({"run_id": "r1", "action": "asset_publish", "asset_id": "a1"})
        raw = get_log_path().read_text(encoding="utf-8")
        assert raw.endswith("\n")
        parsed = json.loads(raw.strip())
        assert parsed["run_id"] == "r1"
        assert parsed["action"] == "asset_publish"
        assert parsed["asset_id"] == "a1"
        assert isinstance(parsed["timestamp"], str)
        datetime.fromisoformat(parsed["timestamp"].replace("Z", "+00:00"))

    def test_appends_subsequent_records(self) -> None:
        log_asset_call({"run_id": "r1", "action": "hub_search_hit"})
        log_asset_call({"run_id": "r1", "action": "asset_reuse"})
        log_asset_call({"run_id": "r2", "action": "asset_publish"})
        lines = [
            line for line in get_log_path().read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        assert len(lines) == 3

    def test_creates_missing_nested_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nested = tmp_path / "nested" / "deep"
        monkeypatch.setenv("EVOLUTION_DIR", str(nested))
        log_asset_call({"run_id": "r1", "action": "hub_search_miss"})
        assert get_log_path().exists()

    def test_no_ops_on_invalid_entry_without_throwing(self) -> None:
        log_asset_call(None)
        log_asset_call("not-an-object")  # type: ignore[arg-type]
        log_asset_call(42)  # type: ignore[arg-type]
        assert not get_log_path().exists()


class TestReadCallLog:
    def test_empty_when_file_missing(self) -> None:
        assert read_call_log() == []

    def test_parses_all_valid_lines(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        log_asset_call({"run_id": "r2", "action": "b"})
        assert len(read_call_log()) == 2

    def test_skips_corrupt_lines(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        with get_log_path().open("a", encoding="utf-8") as handle:
            handle.write("not-json-at-all\n")
        log_asset_call({"run_id": "r2", "action": "b"})
        entries = read_call_log()
        assert len(entries) == 2
        assert entries[0]["run_id"] == "r1"
        assert entries[1]["run_id"] == "r2"

    def test_filters_by_run_id(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        log_asset_call({"run_id": "r2", "action": "a"})
        log_asset_call({"run_id": "r1", "action": "b"})
        entries = read_call_log({"run_id": "r1"})
        assert len(entries) == 2
        assert all(entry["run_id"] == "r1" for entry in entries)

    def test_filters_by_action(self) -> None:
        log_asset_call({"run_id": "r1", "action": "asset_reuse"})
        log_asset_call({"run_id": "r1", "action": "asset_publish"})
        entries = read_call_log({"action": "asset_reuse"})
        assert len(entries) == 1
        assert entries[0]["action"] == "asset_reuse"

    def test_filters_by_since_inclusive(self) -> None:
        now = datetime.now(UTC)
        old = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        recent = now.isoformat().replace("+00:00", "Z")
        get_log_path().parent.mkdir(parents=True, exist_ok=True)
        get_log_path().write_text(
            json.dumps({"timestamp": old, "run_id": "r1", "action": "a"})
            + "\n"
            + json.dumps({"timestamp": recent, "run_id": "r2", "action": "a"})
            + "\n",
            encoding="utf-8",
        )
        since = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        entries = read_call_log({"since": since})
        assert len(entries) == 1
        assert entries[0]["run_id"] == "r2"

    def test_ignores_invalid_since(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        log_asset_call({"run_id": "r2", "action": "b"})
        assert len(read_call_log({"since": "not-a-date"})) == 2

    def test_applies_last_n_after_filters(self) -> None:
        for index in range(5):
            log_asset_call({"run_id": "r1", "action": "a", "seq": index})
        entries = read_call_log({"last": 2})
        assert len(entries) == 2
        assert entries[0]["seq"] == 3
        assert entries[1]["seq"] == 4

    def test_combines_run_id_and_action_filters(self) -> None:
        log_asset_call({"run_id": "r1", "action": "asset_reuse"})
        log_asset_call({"run_id": "r1", "action": "asset_publish"})
        log_asset_call({"run_id": "r2", "action": "asset_reuse"})
        entries = read_call_log({"run_id": "r1", "action": "asset_reuse"})
        assert len(entries) == 1
        assert entries[0]["run_id"] == "r1"
        assert entries[0]["action"] == "asset_reuse"


class TestSummarizeCallLog:
    def test_zeroed_summary_on_empty_log(self) -> None:
        summary = summarize_call_log()
        assert summary["total_entries"] == 0
        assert summary["unique_assets"] == 0
        assert summary["unique_runs"] == 0
        assert summary["by_action"] == {}

    def test_counts_totals_and_buckets(self) -> None:
        log_asset_call({"run_id": "r1", "action": "asset_reuse", "asset_id": "a1"})
        log_asset_call({"run_id": "r1", "action": "asset_reuse", "asset_id": "a2"})
        log_asset_call({"run_id": "r2", "action": "asset_publish", "asset_id": "a1"})
        summary = summarize_call_log()
        assert summary["total_entries"] == 3
        assert summary["unique_assets"] == 2
        assert summary["unique_runs"] == 2
        assert summary["by_action"]["asset_reuse"] == 2
        assert summary["by_action"]["asset_publish"] == 1

    def test_labels_missing_action_as_unknown(self) -> None:
        log_asset_call({"run_id": "r1"})
        assert summarize_call_log()["by_action"]["unknown"] == 1

    def test_passes_filters_through(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        log_asset_call({"run_id": "r2", "action": "a"})
        summary = summarize_call_log({"run_id": "r1"})
        assert summary["total_entries"] == 1
        assert summary["unique_runs"] == 1

    def test_includes_entries_array(self) -> None:
        log_asset_call({"run_id": "r1", "action": "a"})
        summary = summarize_call_log()
        assert isinstance(summary["entries"], list)
        assert len(summary["entries"]) == 1


class TestReuseAttributionSummary:
    def test_empty_rollup(self) -> None:
        rollup = reuse_attribution_summary()
        assert rollup == {
            "total_reuse": 0,
            "total_reference": 0,
            "total_tokens_saved": 0,
            "by_asset": [],
        }

    def test_aggregates_per_asset_and_sorts_by_activity(self) -> None:
        log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_reuse",
                "asset_id": "a1",
                "source_node_id": "n1",
                "tokens_saved": 100,
            }
        )
        log_asset_call({"run_id": "r1", "action": "asset_reference", "asset_id": "a1"})
        log_asset_call(
            {"run_id": "r2", "action": "asset_reuse", "asset_id": "a2", "tokens_saved": 30}
        )
        log_asset_call({"run_id": "r2", "action": "asset_publish", "asset_id": "a3"})
        rollup = reuse_attribution_summary()
        assert rollup["total_reuse"] == 2
        assert rollup["total_reference"] == 1
        assert rollup["total_tokens_saved"] == 130
        assert [row["asset_id"] for row in rollup["by_asset"]] == ["a1", "a2"]
        first = rollup["by_asset"][0]
        assert first["reuse"] == 1
        assert first["reference"] == 1
        assert first["tokens_saved"] == 100
        assert first["source_node_id"] == "n1"

    def test_keeps_first_seen_source_and_chain(self) -> None:
        log_asset_call({"action": "asset_reuse", "asset_id": "a1", "source_node_id": "n1"})
        log_asset_call({"action": "asset_reuse", "asset_id": "a1", "source_node_id": "n2"})
        rollup = reuse_attribution_summary()
        assert rollup["by_asset"][0]["source_node_id"] == "n1"

    def test_ignores_non_positive_tokens_saved(self) -> None:
        log_asset_call({"action": "asset_reuse", "asset_id": "a1", "tokens_saved": -5})
        log_asset_call({"action": "asset_reuse", "asset_id": "a1", "tokens_saved": "bad"})
        rollup = reuse_attribution_summary()
        assert rollup["total_tokens_saved"] == 0
        assert rollup["by_asset"][0]["tokens_saved"] == 0


class TestAssetCostIndex:
    def test_maps_publish_tokens_spent_later_rows_win(self) -> None:
        log_asset_call({"action": "asset_publish", "asset_id": "a1", "tokens_spent": 500})
        log_asset_call({"action": "asset_publish", "asset_id": "a1", "tokens_spent": 700})
        log_asset_call({"action": "asset_publish", "asset_id": "a2", "tokens_spent": 0})
        log_asset_call({"action": "asset_reuse", "asset_id": "a3", "tokens_spent": 900})
        index = asset_cost_index()
        assert index == {"a1": 700}


class TestCliAssetLog:
    def test_cli_reads_call_log_not_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_reuse",
                "asset_id": "sha256:abcdef0123456789",
                "signals": ["log_error", "refactor"],
            }
        )
        assert main(["asset-log"]) == 0
        out = capsys.readouterr().out
        assert "Asset Call Log" in out
        assert "asset_call_log.jsonl" in out
        assert "asset_reuse: 1" in out
        assert "run=r1" in out

    def test_cli_json_mode_outputs_raw_entries(self, capsys: pytest.CaptureFixture[str]) -> None:
        log_asset_call({"run_id": "r1", "action": "asset_publish", "asset_id": "a1"})
        log_asset_call({"run_id": "r2", "action": "asset_reuse", "asset_id": "a2"})
        assert main(["asset-log", "--json", "--action=asset_reuse"]) == 0
        parsed = json.loads(capsys.readouterr().out)
        assert len(parsed) == 1
        assert parsed[0]["run_id"] == "r2"

    def test_cli_last_filter(self, capsys: pytest.CaptureFixture[str]) -> None:
        for index in range(5):
            log_asset_call({"run_id": f"r{index}", "action": "a"})
        assert main(["asset-log", "--json", "--last=2"]) == 0
        parsed = json.loads(capsys.readouterr().out)
        assert [entry["run_id"] for entry in parsed] == ["r3", "r4"]
