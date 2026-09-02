"""S30 paired comparison: exact binomial on discordant pairs."""

from __future__ import annotations

import json
from math import comb
from pathlib import Path

import pytest

from evolver.bench.compare import binom_two_sided, compare_runs


def test_binom_known_values() -> None:
    # wikiskill contract: (10, 0) → 2 / 2**10
    assert binom_two_sided(0, 10) == pytest.approx(2 * comb(10, 0) / 2**10)
    assert binom_two_sided(10, 10) == pytest.approx(2 / 2**10)
    # perfectly balanced → largest possible p
    assert binom_two_sided(5, 10) == pytest.approx(1.0)
    assert binom_two_sided(0, 0) == 1.0


def _results(prefix: str, passes: dict[str, bool]) -> dict:
    return {
        "per_task": [
            {"id": f"{prefix}{i}", "score": 1.0 if ok else 0.0} for i, ok in passes.items()
        ]
    }


def test_compare_significant_a_better() -> None:
    a = _results("t", {str(i): True for i in range(10)})
    b = _results("t", {str(i): False for i in range(10)})
    verdict = compare_runs(a, b)
    assert verdict["wins_a"] == 10
    assert verdict["wins_b"] == 0
    assert verdict["p"] == pytest.approx(2 / 2**10)
    assert verdict["verdict"] == "a_better"


def test_compare_balanced_is_no_difference() -> None:
    # 5 discordant each way → p = 2*(C(10,0)+...+C(10,5))/2**10 > 0.05
    a = _results("t", {str(i): i % 2 == 0 for i in range(10)})
    b = _results("t", {str(i): i % 2 == 1 for i in range(10)})
    verdict = compare_runs(a, b)
    assert verdict["verdict"] == "no_significant_difference"
    assert verdict["ties"] == 0


def test_compare_all_ties() -> None:
    a = _results("t", {str(i): True for i in range(5)})
    b = _results("t", {str(i): True for i in range(5)})
    verdict = compare_runs(a, b)
    assert verdict["discordant"] == 0
    assert verdict["p"] == 1.0
    assert verdict["verdict"] == "no_significant_difference"


def test_compare_rejects_mismatched_task_sets() -> None:
    a = _results("t", {"1": True})
    b = _results("t", {"2": True})
    with pytest.raises(ValueError, match="task sets differ"):
        compare_runs(a, b)


# ---------------------------------------------------------------------------
# CLI roundtrip: run --output → compare
# ---------------------------------------------------------------------------


def _pack(tmp_path: Path) -> Path:
    tasks = [
        {
            "id": f"val-{i}",
            "split": "val",
            "title": "t",
            "prompt": "write out.txt",
            "sandbox": {"spec.txt": "x"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "ok"},
        }
        for i in range(6)
    ]
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


def test_run_output_then_compare_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.cli import main

    evo = tmp_path / "evo"
    evo.mkdir(parents=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    pack = _pack(tmp_path)

    # Baseline run: sandboxes materialized, everything wrong.
    monkeypatch.chdir(tmp_path)
    from evolver.bench.tasks import materialize, validate_tasks

    tasks = json.loads(pack.read_text(encoding="utf-8"))
    assert validate_tasks(tasks) == []
    for t in tasks:
        materialize(t, tmp_path / "sandboxes")
        (tmp_path / "sandboxes" / t["id"] / "out.txt").write_text("WRONG", encoding="utf-8")
    assert (
        main(
            [
                "bench",
                "run",
                "--pack",
                str(pack),
                "--no-record",
                "--output",
                str(tmp_path / "base.json"),
            ]
        )
        == 1
    )

    # Mutated run: everything right (agent wrote correct deliverables).
    for t in tasks:
        (tmp_path / "sandboxes" / t["id"] / "out.txt").write_text("ok", encoding="utf-8")
    assert (
        main(
            [
                "bench",
                "run",
                "--pack",
                str(pack),
                "--no-record",
                "--output",
                str(tmp_path / "mut.json"),
            ]
        )
        == 0
    )

    capsys.readouterr()
    assert main(["bench", "compare", str(tmp_path / "base.json"), str(tmp_path / "mut.json")]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["verdict"] == "b_better"
    assert verdict["wins_b"] == 6
    assert verdict["p"] == pytest.approx(2 / 2**6)
