"""Shared pytest fixtures."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _neutral_fitness_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    """S26: the fitness cascade is the DEFAULT solidify validation path.

    Sandboxed test workspaces have no src/tests for ruff/mypy/pytest to
    inspect, so swap in a workspace-neutral command set globally. Tests that
    exercise cascade mechanics monkeypatch FITNESS_CASCADE_COMMANDS again;
    legacy-path tests set enable_fitness_cascade=False explicitly.
    """
    from evolver.gep import solidify as solidify_mod

    neutral: list[dict[str, Any]] = [
        {"command": [sys.executable, "-c", "print('ok')"]},
    ]
    monkeypatch.setattr(solidify_mod, "FITNESS_CASCADE_COMMANDS", neutral)


@pytest.fixture(autouse=True)
def _restore_feature_flags() -> Iterator[None]:
    """Round-26 (DEBUG #37b): set_flag(persist=False) mutates a process-wide
    in-memory flag cache with NO undo — a test leaving enable_fitness_cascade
    off silently rerouted later tests onto the legacy solidify path (a wiki
    shadow-rejection test lost its entry; latent until the two files ran
    adjacently). Snapshot the cache around every test: for flags what
    monkeypatch is for environment variables."""
    from evolver.gep import feature_flags as ff

    # test-side snapshot of the private in-memory flag cache
    with ff._lock:
        snapshot = dict(ff._disk_flags)
    yield
    with ff._lock:
        ff._disk_flags = snapshot
        ff._disk_flags_loaded_at = ff.time.monotonic()


@pytest.fixture(autouse=True, scope="session")
def _shield_ambient_load() -> Iterator[None]:
    """Full-cycle tests (run/cli/integration) must not preflight-abort on
    ambient host load. test_guards.py pins EVOLVE_LOAD_MAX=0.01 itself to
    cover the load-abort path deterministically."""
    mp = pytest.MonkeyPatch()
    mp.setenv("EVOLVE_LOAD_MAX", "999")
    yield
    mp.undo()


@pytest.fixture(autouse=True, scope="session")
def _production_wiki_tripwire() -> Iterator[None]:
    """Round-26 (DEBUG #37): a test once drove the real cascade-failure path
    without env isolation and appended its fixture rejections ("gene-1") to
    the PRODUCTION wiki — 128 of 161 skill-impact entries were that noise by
    the time it was caught. The suite must never write runtime state outside
    its sandboxes: snapshot the real wiki's entry count at session start and
    assert it unchanged at teardown. Redirect is a deliberate non-goal —
    env-driven wiki tests (test_wiki.py) manage their own paths."""
    import os

    if os.environ.get("EVOLUTION_DIR"):
        # An outer harness already isolated the evolution dir.
        yield
        return
    from evolver.gep.paths import get_evolution_dir

    path = get_evolution_dir() / "wiki" / "skill-impact.md"

    def _entries() -> int:
        if not path.is_file():
            return 0
        return sum(
            1
            for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.startswith("## ")
        )

    before = _entries()
    yield
    after = _entries()
    assert after == before, (
        f"production wiki gained {after - before} entr{'y' if after - before == 1 else 'ies'} "
        "during the test session — a test wrote runtime state without isolating "
        "its wiki/evolution-dir path (request temp_workspace or monkeypatch the writer)"
    )


@pytest.fixture
def temp_workspace(monkeypatch: pytest.MonkeyPatch) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
        monkeypatch.setenv("MEMORY_DIR", str(ws / "memory"))
        monkeypatch.setenv("EVOLUTION_DIR", str(ws / "memory" / "evolution"))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(ws / ".evolver" / "gep"))
        monkeypatch.setenv("EVOLVER_LOGS_DIR", str(ws / "logs"))
        monkeypatch.setenv("EVOLVER_SETTINGS_DIR", str(ws / ".evolver_settings"))
        monkeypatch.setenv("EVOLVER_HOME", str(ws / ".evomap"))
        yield ws
