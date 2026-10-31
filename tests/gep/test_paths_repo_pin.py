"""Tests for EVOLVER_REPO_ROOT pin precedence over WORKSPACE_DIR."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evolver.gep import paths as paths_mod


@pytest.fixture()
def product_and_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Setup: product checkout and scratch workspace, pin product via EVOLVER_REPO_ROOT."""
    product = tmp_path / "evolver.py"
    product.mkdir()
    (product / ".git").mkdir()
    scratch = tmp_path / "workspace"
    scratch.mkdir()
    (scratch / ".git").mkdir()
    monkeypatch.chdir(scratch)
    monkeypatch.setenv("WORKSPACE_DIR", str(scratch))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(product))
    monkeypatch.setenv("EVOLVER_QUIET_PARENT_GIT", "1")
    return product.resolve(), scratch.resolve()


def test_workspace_root_follows_evolver_repo_root_over_workspace_dir(product_and_scratch):
    """get_workspace_root must prefer EVOLVER_REPO_ROOT over WORKSPACE_DIR."""
    product, _scratch = product_and_scratch
    assert paths_mod.get_workspace_root() == product
    assert paths_mod.get_repo_root(_quiet=True) == product


def test_workspace_id_stable_on_product_pin(product_and_scratch, monkeypatch):
    """Workspace ID must remain stable when EVOLVER_REPO_ROOT is pinned."""
    product, _ = product_and_scratch
    wid = paths_mod.compute_workspace_id()
    # Change scratch path, ID should not change
    monkeypatch.setenv("WORKSPACE_DIR", str(Path("/tmp/other-scratch")))
    assert paths_mod.compute_workspace_id() == wid
    # Explicit product argument also gives same ID
    assert wid == paths_mod.compute_workspace_id(product)
