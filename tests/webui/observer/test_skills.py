"""Tests for evolver.webui.observer.skills."""

from __future__ import annotations

from pathlib import Path

from evolver.webui.observer.skills import skills_status


class TestSkillsStatus:
    def test_empty_dir(self, tmp_path: Path):
        result = skills_status(skills_dir=tmp_path)
        assert result["total"] == 0
        assert result["skills"] == []

    def test_with_skills(self, tmp_path: Path):
        skill_a = tmp_path / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text("# Skill A\n")

        skill_b = tmp_path / "skill-b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text("# Skill B\n\nDesc")

        # Non-skill directory (no SKILL.md)
        (tmp_path / "not-a-skill").mkdir()

        result = skills_status(skills_dir=tmp_path)
        assert result["total"] == 2
        names = {s["id"] for s in result["skills"]}
        assert names == {"skill-a", "skill-b"}

        # Verify length is recorded
        lengths = {s["skill_md_length"] for s in result["skills"]}
        assert len(lengths) == 2
