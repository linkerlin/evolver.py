"""Tests for ops/skills_monitor.py.

Equivalent test source: test/skillsMonitor.test.js.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops.skills_monitor import (
    _check_node_modules,
    _check_skill_md,
    _check_venv,
    _create_skill_md,
    auto_fix_skills,
    check_skills_health,
)


@pytest.fixture
def temp_repo_with_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    skills = repo / "skills"
    skills.mkdir()

    # Node skill
    node_skill = skills / "my-node-skill"
    node_skill.mkdir()
    (node_skill / "package.json").write_text('{"name": "my-node-skill"}', encoding="utf-8")

    # Python skill
    py_skill = skills / "my-py-skill"
    py_skill.mkdir()
    (py_skill / "pyproject.toml").write_text('[project]\nname = "my-py-skill"\n', encoding="utf-8")
    (py_skill / "SKILL.md").write_text(
        "# my-py-skill\n\n## Description\n\nTest skill with enough content.\n", encoding="utf-8"
    )

    # Skill with missing SKILL.md
    bare_skill = skills / "bare-skill"
    bare_skill.mkdir()
    (bare_skill / "package.json").write_text('{"name": "bare-skill"}', encoding="utf-8")

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return repo


class TestCheckSkillsHealth:
    def test_detects_skills_dir(self, temp_repo_with_skills: Path) -> None:
        result = check_skills_health()
        assert result["ok"] is False  # has issues (missing node_modules, missing skill_md)
        assert result["total_skills"] == 3
        dirs = {s["dir"] for s in result["skills"]}
        assert "skills/my-node-skill" in dirs
        assert "skills/my-py-skill" in dirs
        assert "skills/bare-skill" in dirs

    def test_no_repo_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_REPO_ROOT", "")
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
        result = check_skills_health()
        assert result["ok"] is False
        assert result["error"] == "no_repo_root"


class TestCheckSkillMd:
    def test_ok(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "# Skill\n\n## Description\n\n"
            "A good skill with enough content to pass the minimum length check.\n",
            encoding="utf-8",
        )
        ok, status = _check_skill_md(d)
        assert ok is True
        assert status == "ok"

    def test_missing(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        ok, status = _check_skill_md(d)
        assert ok is False
        assert status == "missing"

    def test_too_short(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("hi", encoding="utf-8")
        ok, status = _check_skill_md(d)
        assert ok is False
        assert status == "too_short"


class TestCheckNodeModules:
    def test_ok(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "package.json").write_text("{}", encoding="utf-8")
        (d / "node_modules").mkdir()
        ok, status = _check_node_modules(d)
        assert ok is True
        assert status == "ok"

    def test_missing(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "package.json").write_text("{}", encoding="utf-8")
        ok, status = _check_node_modules(d)
        assert ok is False
        assert status == "missing_node_modules"


class TestCheckVenv:
    def test_ok(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (d / ".venv").mkdir()
        ok, status = _check_venv(d)
        assert ok is True
        assert status == "ok"

    def test_missing(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        (d / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        ok, status = _check_venv(d)
        assert ok is False
        assert status == "missing_venv"


class TestAutoFixSkills:
    def test_dry_run(self, temp_repo_with_skills: Path) -> None:
        result = auto_fix_skills(dry_run=True)
        assert result["dry_run"] is True
        assert len(result["fixes"]) > 0
        assert all(f.get("ok") for f in result["fixes"])

    def test_creates_skill_md(self, temp_repo_with_skills: Path) -> None:
        bare = temp_repo_with_skills / "skills" / "bare-skill"
        assert not (bare / "SKILL.md").exists()
        result = auto_fix_skills(dry_run=False)
        fix_dirs = {f["dir"] for f in result["fixes"]}
        assert "skills/bare-skill" in fix_dirs
        assert (bare / "SKILL.md").exists()

    def test_create_skill_md_helper(self, tmp_path: Path) -> None:
        d = tmp_path / "skill"
        d.mkdir()
        result = _create_skill_md(d)
        assert result["ok"] is True
        assert (d / "SKILL.md").exists()
        content = (d / "SKILL.md").read_text(encoding="utf-8")
        assert "## Description" in content
