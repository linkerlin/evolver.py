"""Tests for charter_check module and CLI integration (演进方案.md §11.4 P1)."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.cli import main
from evolver.ops.charter_check import (
    build_charter_report,
    count_unique_evolver_envs,
    format_charter_report,
)


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
