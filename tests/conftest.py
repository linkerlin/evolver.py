"""Shared pytest fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


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
