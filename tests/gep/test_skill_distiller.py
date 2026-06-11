"""Tests for evolver.gep.skill_distiller."""

from evolver.gep.skill_distiller import (
    DistilledSkill,
    distill_and_save,
    distill_skill,
    save_skill,
)


class TestDistillSkill:
    def test_extracts_rules(self):
        text = "You should always validate input.\nNever trust user data."
        skill = distill_skill(text)
        assert skill is not None
        assert any("validate" in h for h in skill.heuristics)
        assert any("never trust" in h.lower() for h in skill.heuristics)

    def test_extracts_triggers(self):
        text = "How do I validate input?\nCan you check this?"
        skill = distill_skill(text)
        assert skill is not None
        assert any("validate" in t for t in skill.triggers)

    def test_no_rules_returns_none(self):
        assert distill_skill("hello world") is None

    def test_generalises(self):
        text = "You should always validate input in my_project_v2."
        skill = distill_skill(text)
        assert "my_project_v2" not in skill.examples[0]

    def test_name_override(self):
        text = "Always use pytest."
        skill = distill_skill(text, name="testing_skill")
        assert skill.name == "testing_skill"


class TestSaveSkill:
    def test_saves_markdown(self, tmp_path):
        skill = DistilledSkill(
            name="test_skill",
            intent="Test intent.",
            triggers=["do test"],
            heuristics=["always test"],
            examples=["example code"],
            source_hash="abc123",
        )
        path = save_skill(skill, output_dir=tmp_path, overwrite=True)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "# test_skill" in content
        assert "Test intent." in content
        assert "always test" in content

    def test_no_overwrite(self, tmp_path):
        skill = DistilledSkill(
            name="existing",
            intent="Intent.",
            triggers=[],
            heuristics=[],
            examples=[],
            source_hash="abc",
        )
        path = save_skill(skill, output_dir=tmp_path)
        # Second save without overwrite should return same path
        path2 = save_skill(skill, output_dir=tmp_path, overwrite=False)
        assert path == path2


class TestDistillAndSave:
    def test_end_to_end(self, tmp_path):
        text = "You should always use type hints."
        path = distill_and_save(text, name="type_hints", output_dir=tmp_path)
        assert path is not None
        assert path.exists()
        assert "type_hints.md" in str(path)

    def test_no_content(self, tmp_path):
        assert distill_and_save("hello world", output_dir=tmp_path) is None
