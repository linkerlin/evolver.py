"""Skill asset bridge — multi-root priority discovery + store sync (v1.104.0).

EvoX SkillRegistry concept harvest: project > user > builtin priority with
same-name shadowing; conversion delegated to the existing skill2gep layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.skill_assets import (
    SKILL_GENE_PREFIX,
    discover_skills,
    list_skill_genes,
    skill_roots,
    sync_skills,
)

ALPHA_PROJ = """---
name: alpha
description: Fix ImportError problems in Python imports quickly
---
# Alpha
- step one
"""

ALPHA_USER = """---
name: alpha
description: Lower-priority shadowed variant
---
# Alpha (user)
"""

BETA_USER = """---
name: beta
description: Optimize timeout and slow latency issues
---
# Beta
- step one
"""


@pytest.fixture
def skill_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "ws"
    user = tmp_path / "user-skills"
    proj_alpha = project / ".agents" / "skills" / "alpha"
    proj_alpha.mkdir(parents=True)
    (proj_alpha / "SKILL.md").write_text(ALPHA_PROJ, encoding="utf-8")
    user_alpha = user / "alpha"
    user_alpha.mkdir(parents=True)
    (user_alpha / "SKILL.md").write_text(ALPHA_USER, encoding="utf-8")
    user_beta = user / "beta"
    user_beta.mkdir(parents=True)
    (user_beta / "SKILL.md").write_text(BETA_USER, encoding="utf-8")

    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(project))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    # SKILL_ROOTS_OVERRIDE is evaluated at config-import time; patch the
    # module attribute (established repo pattern) so discovery stays isolated
    # from the machine's real user-level skill directories.
    monkeypatch.setattr(
        "evolver.config.SKILL_ROOTS_OVERRIDE",
        f"{project / '.agents' / 'skills'}:{user}",
    )
    return tmp_path


class TestDiscovery:
    def test_priority_shadowing(self, skill_env: Path) -> None:
        skills = discover_skills()
        by_name = {s["name"]: s for s in skills}
        assert set(by_name) == {"alpha", "beta"}
        # project-level alpha shadows the user-level one
        assert by_name["alpha"]["level"] == "override"
        assert ".agents" in by_name["alpha"]["path"]
        assert by_name["beta"]["level"] == "override"

    def test_override_ordering_defines_priority(self, skill_env: Path) -> None:
        roots = skill_roots()
        assert all(level == "override" for level, _ in roots)
        assert ".agents" in str(roots[0][1])

    def test_default_roots_cover_project_and_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.SKILL_ROOTS_OVERRIDE", "")
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
        roots = skill_roots()
        levels = [level for level, _ in roots]
        assert levels[0] == "project"
        assert "user" in levels and "builtin" in levels


class TestSync:
    def test_sync_dry_run_installs_nothing(self, skill_env: Path) -> None:
        baseline = {g["id"] for g in list_skill_genes()}  # seed s2g genes stay
        result = sync_skills(dry_run=True)
        assert result["ok"] is True
        assert result["discovered"] == 2
        assert all(i["action"] == "would_install" for i in result["installed"])
        assert {g["id"] for g in list_skill_genes()} == baseline

    def test_sync_installs_valid_genes(self, skill_env: Path) -> None:
        result = sync_skills()
        assert result["ok"] is True
        assert {i["name"] for i in result["installed"]} == {"alpha", "beta"}

        genes = list_skill_genes()
        names = {g["skill_name"] for g in genes}
        assert {"alpha", "beta"} <= names  # seed s2g genes may coexist
        alpha_genes = [g for g in genes if g["skill_name"] == "alpha"]
        assert alpha_genes and alpha_genes[0]["id"].startswith(SKILL_GENE_PREFIX)

        # Content-hash validity: load_genes must return them (it silently
        # skips entries whose asset_id hash mismatches) and the shape must be
        # schema-compatible.
        from evolver.gep.asset_store import load_genes

        stored = {g["id"]: g for g in load_genes()}
        alpha_id = f"{SKILL_GENE_PREFIX}alpha"
        assert alpha_id in stored
        assert stored[alpha_id]["type"] == "Gene"
        assert isinstance(stored[alpha_id]["signals_match"], list)

    def test_shadowed_variant_not_synced(self, skill_env: Path) -> None:
        sync_skills()
        from evolver.gep.asset_store import load_genes

        alphas = [g for g in load_genes() if g["id"] == f"{SKILL_GENE_PREFIX}alpha"]
        assert len(alphas) == 1
        # Project-level description won (not the shadowed user variant).
        assert "ImportError" in alphas[0]["summary"]

    def test_resync_is_idempotent(self, skill_env: Path) -> None:
        first = sync_skills()
        second = sync_skills()
        assert first["discovered"] == second["discovered"] == 2
        from evolver.gep.asset_store import load_genes

        synced = [
            g
            for g in load_genes()
            if g["id"] in {f"{SKILL_GENE_PREFIX}alpha", f"{SKILL_GENE_PREFIX}beta"}
        ]
        assert len(synced) == 2
