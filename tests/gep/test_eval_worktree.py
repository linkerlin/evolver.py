"""S26.5: evaluate in a clean git worktree (HEAD + mutation overlay)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evolver.gep.eval_worktree import is_runtime_rel, isolated_eval_cwd


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(ws: Path) -> Path:
    _git(ws, "init")
    _git(ws, "config", "user.email", "t@t")
    _git(ws, "config", "user.name", "t")
    (ws / "src").mkdir()
    (ws / "src" / "app.py").write_text("HEAD = 1\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return ws


def test_runtime_rel_filters() -> None:
    assert is_runtime_rel("memory/evolution/feedback.jsonl") is True
    assert is_runtime_rel("evolver/.config/stake_state.json") is True
    assert is_runtime_rel("src/evolver/cli.py") is False


def test_flag_off_returns_live_cwd(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_EVAL_WORKTREE", "0")
    ws = _repo(temp_workspace)
    with isolated_eval_cwd(ws) as (cwd, meta):
        assert cwd == ws
        assert meta["isolated"] is False
        assert meta["reason"] == "flag_off"


def test_worktree_overlays_mutation_not_runtime(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_EVAL_WORKTREE", "1")
    ws = _repo(temp_workspace)
    (ws / "src" / "app.py").write_text("MUTATED = 1\n", encoding="utf-8")
    junk = ws / "memory" / "evolution" / "feedback.jsonl"
    junk.parent.mkdir(parents=True)
    junk.write_text("{}\n", encoding="utf-8")

    with isolated_eval_cwd(ws) as (cwd, meta):
        assert meta["isolated"] is True
        assert cwd != ws
        assert (cwd / "src" / "app.py").read_text(encoding="utf-8") == "MUTATED = 1\n"
        assert not (cwd / "memory" / "evolution" / "feedback.jsonl").exists()
        # HEAD original still on live tree after overlay (live file is mutated too)
        assert (ws / "src" / "app.py").read_text(encoding="utf-8") == "MUTATED = 1\n"

    # worktree removed
    assert not Path(meta["path"]).exists()


def test_not_git_falls_back(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_EVAL_WORKTREE", "1")
    with isolated_eval_cwd(temp_workspace) as (cwd, meta):
        assert cwd == temp_workspace
        assert meta["isolated"] is False
        assert meta["reason"] == "not_a_git_repo"


def test_default_enabled_isolates_in_worktree(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVOLVER_FF_ENABLE_EVAL_WORKTREE", raising=False)
    ws = _repo(temp_workspace)
    with isolated_eval_cwd(ws) as (cwd, meta):
        assert meta["isolated"] is True
        assert meta["reason"] == "worktree"
        assert cwd != ws
        assert Path(meta["path"]).exists()
    assert not Path(meta["path"]).exists()


def test_fallback_with_dirty_runtime_records_and_warns(
    temp_workspace: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _repo(temp_workspace)
    # create dirty uncommitted runtime file
    dirty_file = ws / "memory" / "evolution" / "feedback.jsonl"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text('{"dirty": true}\n', encoding="utf-8")

    # simulate worktree command failure
    import evolver.gep.eval_worktree as ewt

    def _fail_cmd(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("git worktree failed deliberately")

    monkeypatch.setattr(ewt, "run_cmd", _fail_cmd)

    with isolated_eval_cwd(ws) as (cwd, meta):
        assert cwd == ws
        assert meta["isolated"] is False
        assert meta["reason"] == "fallback:RuntimeError"
        assert "git worktree failed deliberately" in meta["error"]
        assert any("memory/evolution/feedback.jsonl" in p for p in meta["dirty_runtime"])

    captured = capsys.readouterr()
    assert "[eval_worktree] WARNING: worktree isolation failed" in captured.err
    assert "live tree dirty with" in captured.err


def test_strict_mode_raises(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _repo(temp_workspace)
    monkeypatch.setenv("EVOLVER_EVAL_WORKTREE_STRICT", "1")

    import evolver.gep.eval_worktree as ewt

    def _fail_cmd(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated boom")

    monkeypatch.setattr(ewt, "run_cmd", _fail_cmd)

    with pytest.raises(RuntimeError, match="eval_worktree strict isolation failed: simulated boom"):
        with isolated_eval_cwd(ws):
            pass
