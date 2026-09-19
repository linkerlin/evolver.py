"""Tests for charter_check module and CLI integration (演进方案.md §11.4 P1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evolver.cli import main
from evolver.ops.charter_check import (
    LOOP_STALE_THRESHOLD_S,
    build_charter_report,
    count_unique_evolver_envs,
    format_charter_report,
    loop_integrity,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _commit_at(cwd: Path, iso_date: str, msg: str = "c") -> None:
    # The commit must TOUCH the engine surface (src/) — empty commits are
    # invisible to the receipt's `git log -- src tests` pathspec. Both dates
    # are pinned: %cI reads the COMMITTER date; `--date` alone only sets the
    # author date.
    import os

    src = cwd / "src"
    src.mkdir(exist_ok=True)
    (src / "m.py").write_text(f"# {msg}\n", encoding="utf-8")
    _git(cwd, "add", "src")
    env = dict(os.environ, GIT_AUTHOR_DATE=iso_date, GIT_COMMITTER_DATE=iso_date)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", msg],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo(cwd: Path) -> None:
    _git(cwd, "init")
    _git(cwd, "config", "user.email", "t@t.com")
    _git(cwd, "config", "user.name", "T")


def test_count_unique_evolver_envs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(
        "a = os.getenv('EVOLVER_FOO'); b = os.getenv('EVOLVER_BAR')",
        encoding="utf-8",
    )
    (src / "b.py").write_text("c = 'EVOLVER_FOO'; d = 'EVOLVER_BAZ'", encoding="utf-8")
    count = count_unique_evolver_envs(tmp_path)
    assert count == 3


def test_build_charter_report_structure(temp_workspace: Path) -> None:
    report = build_charter_report(repo=temp_workspace, events=[])
    assert "version" in report
    assert "round" in report
    assert "acceptance" in report
    assert "drift" in report
    assert "env_vars" in report
    assert "git_cleanliness" in report
    assert "anchor" in report
    assert "ready_for_promotion" in report

    formatted = format_charter_report(report)
    assert "Charter Machine Receipt" in formatted
    assert "Acceptance Gate" in formatted
    assert "Anchor Suite" in formatted


class TestLoopIntegrity:
    def test_report_carries_loop_integrity_section(self, temp_workspace: Path) -> None:
        report = build_charter_report(repo=temp_workspace, events=[])
        assert "loop_integrity" in report
        formatted = format_charter_report(report)
        assert "Loop Integrity" in formatted

    def test_stale_when_commit_outruns_events(self, tmp_path: Path) -> None:
        # round-30~34 shape: engine commits hours after the last ledger event.
        _init_repo(tmp_path)
        _commit_at(tmp_path, "2026-09-17T10:00:00+00:00", "old loop commit")
        _commit_at(tmp_path, "2026-09-19T12:00:00+00:00", "bypass commit")
        events = [{"timestamp": "2026-09-17T13:44:21.237Z"}]
        receipt = loop_integrity(events, tmp_path)
        assert receipt["status"] == "stale"
        assert receipt["drift_seconds"] > LOOP_STALE_THRESHOLD_S
        assert receipt["last_event"] is not None
        assert receipt["last_engine_commit"] is not None

    def test_ok_when_auto_commit_lags_event_by_seconds(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit_at(tmp_path, "2026-09-17T13:44:30+00:00", "solidify auto-commit")
        events = [{"timestamp": "2026-09-17T13:44:21.237Z"}]
        receipt = loop_integrity(events, tmp_path)
        assert receipt["status"] == "ok"
        assert receipt["drift_seconds"] <= LOOP_STALE_THRESHOLD_S

    def test_no_engine_commits_is_not_stale(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        receipt = loop_integrity([{"timestamp": "2026-09-17T13:44:21.237Z"}], tmp_path)
        assert receipt["status"] == "no_engine_commits"
        assert receipt["drift_seconds"] is None

    def test_no_events_is_not_stale(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit_at(tmp_path, "2026-09-19T12:00:00+00:00", "fresh clone")
        receipt = loop_integrity([], tmp_path)
        assert receipt["status"] == "no_events"

    def test_empty_commit_date_ignored(self, tmp_path: Path) -> None:
        # Events without parseable timestamps must not crash the receipt.
        _init_repo(tmp_path)
        _commit_at(tmp_path, "2026-09-17T13:44:30+00:00")
        events = [{"timestamp": ""}, {"timestamp": "not-a-date"}]
        receipt = loop_integrity(events, tmp_path)
        assert receipt["status"] == "no_events"


def test_cli_charter_check_json(capsys, monkeypatch) -> None:
    rc = main(["charter-check", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "version" in data
    assert "round" in data
    assert "acceptance" in data
    assert "ready_for_promotion" in data


def test_cli_charter_check_text(capsys, monkeypatch) -> None:
    rc = main(["charter-check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Charter Machine Receipt" in out
    assert "Acceptance Gate" in out
