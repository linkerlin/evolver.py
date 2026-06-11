"""Integration tests for evolver.evolve.runner and pipeline stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.evolve.runner import _build_initial_context, run


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state into tmp_path so tests do not touch ~/.evomap."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    yield tmp_path


@pytest.mark.asyncio
async def test_run_single_cycle_emits_prompt(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await run()
    captured = capsys.readouterr()
    assert "BUILT_PROMPT" in captured.out or "sessions_spawn" in captured.out
    assert "GENOME EVOLUTION PROTOCOL" in captured.out


@pytest.mark.asyncio
async def test_run_single_cycle_selects_gene(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await run()
    captured = capsys.readouterr()
    assert "Selected Gene:" in captured.out
    assert "No matching Gene found" not in captured.out


@pytest.mark.asyncio
async def test_run_writes_solidify_state(isolated_evolver_env: Path) -> None:
    await run()
    state_path = isolated_evolver_env / "evolution" / "evolution_solidify_state.json"
    assert state_path.exists()
    import json

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "last_run" in data
    assert data["last_run"].get("signals") is not None
    assert data["last_run"].get("mutation") is not None


def test_build_initial_context_has_required_keys() -> None:
    ctx = _build_initial_context()
    assert ctx["cycle_num"] == 1
    assert ctx["IS_RANDOM_DRIFT"] is False
    assert ctx["IS_DRY_RUN"] is False
    assert ctx["run_id"].startswith("run_")
    assert len(ctx["cycle_id"]) >= 8
