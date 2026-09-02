"""S26.1 bench subsystem: task format, graders, health runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import grade, materialize, validate_tasks
from evolver.bench.runner import run_health
from evolver.gep.fitness_state import fitness_state_path

# ---------------------------------------------------------------------------
# Task pack format
# ---------------------------------------------------------------------------


def _valid_task(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": "spec-format1-1",
        "split": "val",
        "title": "Format products",
        "prompt": "Read spec.md and write output.txt",
        "sandbox": {"spec.md": "alpha|35|active"},
        "grader": {"type": "exact", "file": "output.txt", "expected": "alpha|35|active"},
    }
    task.update(overrides)
    return task


def test_validate_accepts_wellformed_pack() -> None:
    assert validate_tasks([_valid_task(), _valid_task(id="other-1", split="train")]) == []


def test_validate_rejects_bad_packs() -> None:
    dup = _valid_task()
    errors = validate_tasks(
        [
            dup,
            _valid_task(),  # duplicate id
            _valid_task(id="Bad_Slug"),  # not a slug
            _valid_task(id="split-bad", split="dev"),  # bad split
            _valid_task(id="no-sandbox", sandbox={}),  # empty sandbox
            _valid_task(id="bad-grader", grader={"type": "regex", "file": "x"}),  # bad type
            _valid_task(
                id="no-expected", grader={"type": "exact", "file": "x"}
            ),  # missing expected
            _valid_task(
                id="escape",
                sandbox={"../evil.txt": "x"},
            ),  # path escape
        ]
    )
    assert len(errors) == 7
    assert validate_tasks("not a list")  # type: ignore[arg-type]


def test_materialize_writes_sandbox(tmp_path: Path) -> None:
    task = _valid_task(sandbox={"a/b.txt": "hello", "c.txt": "world"})
    sandbox = materialize(task, tmp_path)
    assert (sandbox / "a" / "b.txt").read_text(encoding="utf-8") == "hello"
    assert (sandbox / "c.txt").read_text(encoding="utf-8") == "world"


def test_materialize_force_deletes_stale_artifacts(tmp_path: Path) -> None:
    """Phantom-scoring defense: files the task does not declare must vanish."""
    task = _valid_task()
    sandbox = materialize(task, tmp_path)
    stale = sandbox / "output.txt"
    stale.write_text("STALE GARBAGE", encoding="utf-8")
    materialize(task, tmp_path, force=True)  # re-materialize before grading
    assert not stale.exists()


# ---------------------------------------------------------------------------
# Graders — self-consistency: expected answers MUST score 1.0
# ---------------------------------------------------------------------------


def test_grader_exact_self_consistency(tmp_path: Path) -> None:
    task = _valid_task()
    sandbox = materialize(task, tmp_path)
    (sandbox / "output.txt").write_text("alpha|35|active", encoding="utf-8")
    assert grade(task, sandbox) == 1.0
    (sandbox / "output.txt").write_text("WRONG", encoding="utf-8")
    assert grade(task, sandbox) == 0.0
    (sandbox / "output.txt").unlink()
    assert grade(task, sandbox) == 0.0  # missing deliverable, no crash


def test_grader_contains_json_field_code_stdout(tmp_path: Path) -> Path:
    contains_t = _valid_task(
        id="contains-1",
        grader={"type": "contains", "file": "out.txt", "expected": "needle"},
    )
    s1 = materialize(contains_t, tmp_path)
    (s1 / "out.txt").write_text("haystack needle hay", encoding="utf-8")
    assert grade(contains_t, s1) == 1.0

    json_t = _valid_task(
        id="json-1",
        sandbox={"data.json": '{"a": {"b": [10, 42]}}'},
        grader={"type": "json_field", "file": "data.json", "path": "a.b.1", "expected": 42},
    )
    s2 = materialize(json_t, tmp_path)
    assert grade(json_t, s2) == 1.0

    code_t = _valid_task(
        id="code-1",
        sandbox={"sum.py": "print(1 + 1)"},
        grader={"type": "code_stdout", "file": "", "script": "sum.py", "expected": "2"},
    )
    s3 = materialize(code_t, tmp_path)
    assert grade(code_t, s3) == 1.0
    return s3


def test_grader_code_stdout_timeout_scores_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.bench import scoring

    monkeypatch.setattr(scoring, "CODE_STDOUT_TIMEOUT_S", 0.05)
    task = _valid_task(
        id="slow-1",
        sandbox={"slow.py": "import time; time.sleep(2); print(1)"},
        grader={"type": "code_stdout", "file": "", "script": "slow.py", "expected": "1"},
    )
    sandbox = materialize(task, tmp_path)
    assert grade(task, sandbox) == 0.0


# ---------------------------------------------------------------------------
# Health runner → fitness ledger
# ---------------------------------------------------------------------------


def test_run_health_scores_and_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.bench import runner as runner_mod

    evo = tmp_path / "evo"
    evo.mkdir(parents=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(
        runner_mod,
        "HEALTH_TASKS",
        [
            {"id": "t-ok", "command": [sys.executable, "-c", "print('ok')"], "weight": 1.0},
            {
                "id": "t-fail",
                "command": [sys.executable, "-c", "import sys; sys.exit(3)"],
                "weight": 1.0,
            },
            {"id": "t-missing", "command": ["definitely-not-a-binary-xyz"], "weight": 1.0},
        ],
    )
    result = run_health()
    # runnable tasks: ok + fail; missing is skipped → weight excluded
    assert result["score"] == 0.5
    statuses = {row["id"]: row["status"] for row in result["per_task"]}
    assert statuses == {"t-ok": "pass", "t-fail": "fail", "t-missing": "skipped"}
    assert result["verdict"] is not None
    assert result["verdict"]["verdict"] == "baseline_established"
    from evolver.gep.fitness_state import load_domain

    assert load_domain("bench:health")["r_best"] == 0.5

    # --no-record path: ledger untouched
    before = fitness_state_path().read_text(encoding="utf-8")
    run_health(record=False)
    assert fitness_state_path().read_text(encoding="utf-8") == before


def test_run_health_improvement_updates_rbest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.bench import runner as runner_mod

    evo = tmp_path / "evo"
    evo.mkdir(parents=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(
        runner_mod,
        "HEALTH_TASKS",
        [{"id": "t-ok", "command": [sys.executable, "-c", "print('ok')"], "weight": 1.0}],
    )
    first = run_health()
    assert first["verdict"]["verdict"] == "baseline_established"
    # Same perfect score: strict > → no improvement, still recorded.
    second = run_health()
    assert second["verdict"]["verdict"] == "no_improvement"
    from evolver.gep.fitness_state import load_domain

    assert load_domain("bench:health")["r_best"] == 1.0


def test_pytest_fast_timeout_matches_cascade() -> None:
    """Regression: the health pytest-fast ceiling must equal the solidify
    fitness cascade's — a tighter bench timeout falsely fails a green repo
    (observed 2026-09-02: 300s bench vs ~310s real suite → permanent R=0.5)."""
    from evolver.bench.runner import HEALTH_TASKS
    from evolver.config import FITNESS_PYTEST_TIMEOUT_MS

    spec = next(t for t in HEALTH_TASKS if t["id"] == "health-pytest-fast")
    assert float(spec["timeout_s"]) * 1000.0 == float(FITNESS_PYTEST_TIMEOUT_MS)


def test_pack_roundtrip_from_json(tmp_path: Path) -> None:
    """A wikiskill-format tasks.json imports cleanly (format compatibility)."""
    pack = [_valid_task()]
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert validate_tasks(loaded) == []
    sandbox = materialize(loaded[0], tmp_path / "sandboxes")
    (sandbox / "output.txt").write_text("alpha|35|active", encoding="utf-8")
    assert grade(loaded[0], sandbox) == 1.0
