"""Tests for evolver.gep.validation_env (round-35, DEBUG #41)."""

from __future__ import annotations

import pytest

from evolver.gep.validation_env import validation_env


class TestSoakRoutingNotInherited:
    def test_sentinel_strips_auto_routed_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_SOAK_ROUTED", "1")
        monkeypatch.setenv("EVOLUTION_DIR", "/soak/evolution")
        monkeypatch.setenv("GEP_ASSETS_DIR", "/soak/gep")
        env = validation_env()
        assert "EVOLUTION_DIR" not in env, "engine routing must not reach validation children"
        assert "GEP_ASSETS_DIR" not in env, "engine routing must not reach validation children"

    def test_explicit_vars_forwarded_without_sentinel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOLVER_SOAK_ROUTED", raising=False)
        monkeypatch.setenv("GEP_ASSETS_DIR", "/operator/gep")
        env = validation_env()
        assert env["GEP_ASSETS_DIR"] == "/operator/gep", (
            "explicitly-set values are operator intent and stay forwarded"
        )

    def test_path_prepend_survives_sentinel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import os
        import sys
        from pathlib import Path

        monkeypatch.setenv("EVOLVER_SOAK_ROUTED", "1")
        monkeypatch.setenv("GEP_ASSETS_DIR", "/soak/gep")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        env = validation_env()
        parts = env["PATH"].split(os.pathsep)
        assert parts[0] == str(Path(sys.executable).parent), "PATH normalization is untouched"
        assert "/usr/bin" in parts, "inherited PATH entries are never dropped"
