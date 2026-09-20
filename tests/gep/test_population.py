"""Tests for evolver.gep.population (RSI P1-3 second half, round-41)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from evolver.gep.population import (
    POPULATION_BUDGET_S,
    CandidateResult,
    adjudicate,
    evaluate_candidate,
    run_population,
)


def _r(
    index: int,
    status: str,
    *,
    score: float = 0.0,
    files: int = 0,
) -> CandidateResult:
    return CandidateResult(
        index=index,
        proposal_path=f"p{index}",
        applied=True,
        overall_ok=status == "accepted",
        score=score,
        files_touched=files,
        duration_ms=1,
        status=status,
    )


class TestAdjudicate:
    def test_accepted_beats_rejected(self) -> None:
        assert adjudicate([_r(0, "rejected", score=1.0), _r(1, "accepted")]).index == 1

    def test_score_then_files_then_index(self) -> None:
        assert adjudicate([_r(0, "accepted", score=0.5), _r(1, "accepted", score=0.9)]).index == 1
        assert (
            adjudicate(
                [_r(0, "accepted", score=0.9, files=9), _r(1, "accepted", score=0.9, files=2)]
            ).index
            == 1
        )
        assert (
            adjudicate(
                [_r(7, "accepted", score=0.9, files=2), _r(3, "accepted", score=0.9, files=2)]
            ).index
            == 3
        )

    def test_none_when_no_admissible(self) -> None:
        assert adjudicate([_r(0, "rejected"), _r(1, "apply_failed")]) is None
        assert adjudicate([]) is None


class TestBudgetGuard:
    def test_budget_skip_is_visible(self) -> None:
        clock = {"t": 0.0}

        def now() -> float:
            clock["t"] += POPULATION_BUDGET_S + 1
            return clock["t"]

        judgment = run_population(
            [Path("a.json"), Path("b.json")],
            Path("."),
            cascade_commands=[],
            now=now,
        )
        statuses = [c["status"] for c in judgment["candidates"]]
        assert statuses == ["budget_skipped", "budget_skipped"], statuses
        assert judgment["winner"] is None

    def test_budget_degrades_to_k1_visibly(self) -> None:
        # First candidate evaluates instantly; the clock jumps before #2.
        calls = {"n": 0}

        def now() -> float:
            calls["n"] += 1
            return 0.0 if calls["n"] == 1 else POPULATION_BUDGET_S + 10

        judgment = run_population(
            [Path("a.json"), Path("b.json")],
            Path("."),
            cascade_commands=[],
            now=now,
        )
        statuses = [c["status"] for c in judgment["candidates"]]
        assert "budget_skipped" in statuses and len(statuses) == 2


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _proposal(path: Path, target: str, content: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "action": "patch",
                "gene_id": "gene_pop_test",
                "note": "population e2e",
                "edits": [
                    {"op": "replace", "file": target, "target": "base\n", "content": content}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class TestEvaluateCandidate:
    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "t@t.com")
        _git(repo, "config", "user.name", "T")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", "init")
        return repo

    def _cascade(self) -> list[dict[str, Any]]:
        import sys

        return [{"command": [sys.executable, "-c", "print('ok')"]}]

    def test_accepted_candidate(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        prop = _proposal(tmp_path / "p1.json", "README.md", "candidate one\n")
        result = evaluate_candidate(prop, repo, cascade_commands=self._cascade())
        assert result.status == "accepted", result.detail
        assert result.applied and result.files_touched == 1
        # The live tree must be untouched by population evaluation.
        assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    def test_failed_cascade_rejects(self, tmp_path: Path) -> None:
        import sys

        repo = self._repo(tmp_path)
        prop = _proposal(tmp_path / "p2.json", "README.md", "candidate two\n")
        result = evaluate_candidate(
            prop,
            repo,
            cascade_commands=[{"command": [sys.executable, "-c", "raise SystemExit(3)"]}],
        )
        assert result.status == "rejected"
        assert result.overall_ok is False

    def test_bad_proposal_apply_fails(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        prop = tmp_path / "p3.json"
        prop.write_text(
            json.dumps(
                {
                    "action": "patch",
                    "gene_id": "g",
                    "note": "d",
                    "edits": [
                        {
                            "op": "replace",
                            "file": "README.md",
                            "target": "WILL_NOT_MATCH",
                            "content": "x",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = evaluate_candidate(prop, repo, cascade_commands=self._cascade())
        assert result.status == "apply_failed"
