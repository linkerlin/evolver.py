"""Shared pytest fixtures."""

from __future__ import annotations

import sys
import tempfile
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
