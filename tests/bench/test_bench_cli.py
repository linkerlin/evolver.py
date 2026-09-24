"""S26.1 bench CLI smoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evolver.cli import main


@pytest.fixture
def bench_env(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    from evolver.bench import runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "HEALTH_TASKS",
        [
            {"id": "t-ok", "command": [sys.executable, "-c", "print('ok')"], "weight": 1.0},
        ],
    )
    return temp_workspace


def test_bench_list(bench_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "list"]) == 0
    assert "t-ok" in capsys.readouterr().out


def test_bench_run_records_verdict(bench_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "run"]) == 0  # perfect score → exit 0
    out = capsys.readouterr().out
    assert "baseline_established" in out


def test_bench_run_no_record_leaves_ledger(
    bench_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["bench", "run", "--no-record"]) == 0
    ledger = bench_env / "memory" / "evolution" / "evolution_fitness_state.json"
    assert not ledger.exists()


def test_bench_freeze_is_idempotent(
    bench_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Charter round-79: freeze lands the pack anchor-side, outside the
    workspace; a second freeze is a no-op that refuses to overwrite."""
    home = bench_env / ".evomap-freeze"
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    assert main(["bench", "freeze"]) == 0
    frozen = home / "anchor" / "bench" / "charter-pack.tasks.json"
    assert frozen.exists()
    first = capsys.readouterr().out
    assert "froze 12 tasks" in first
    bytes_before = frozen.read_bytes()
    assert main(["bench", "freeze"]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert frozen.read_bytes() == bytes_before


def test_bench_freeze_force_refreezes(
    bench_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = bench_env / ".evomap-freeze2"
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    assert main(["bench", "freeze"]) == 0
    frozen = home / "anchor" / "bench" / "charter-pack.tasks.json"
    data = json.loads(frozen.read_text(encoding="utf-8"))
    data["tasks"][0]["title"] = "human-refreeze"
    frozen.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert main(["bench", "freeze", "--force"]) == 0
    out = capsys.readouterr().out
    assert "froze 12 tasks" in out
    assert "human-refreeze" not in frozen.read_text(encoding="utf-8")
