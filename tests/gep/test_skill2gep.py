"""Tests for evolver.gep.skill2gep."""

from evolver.gep.skill2gep import (
    SkillGene,
    scan_skills,
    skill_genes_to_selector_pool,
    skill_to_gene,
)


class TestSkillToGene:
    def test_valid_skill(self, tmp_path):
        skill_file = tmp_path / "test_skill.md"
        skill_file.write_text(
            "# Test Skill\n\nThis skill does something useful.\n\n"
            "## Triggers\n\n- Trigger: do something\n",
            encoding="utf-8",
        )
        gene = skill_to_gene(skill_file)
        assert gene is not None
        assert gene.name == "test_skill"
        assert "useful" in gene.intent.lower()
        assert any("do something" in t.lower() for t in gene.trigger_phrases)
        assert gene.confidence == 0.8
        assert gene.gene_id

    def test_missing_file(self):
        assert skill_to_gene("/nonexistent/skill.md") is None

    def test_empty_file(self, tmp_path):
        skill_file = tmp_path / "empty.md"
        skill_file.write_text("", encoding="utf-8")
        assert skill_to_gene(skill_file) is None

    def test_to_gene_dict(self, tmp_path):
        skill_file = tmp_path / "my_skill.md"
        skill_file.write_text("# My Skill\n\nIntent here.\n", encoding="utf-8")
        gene = skill_to_gene(skill_file)
        d = gene.to_gene_dict()
        assert d["name"] == "my_skill"
        assert "epigenetic_marks" in d


class TestScanSkills:
    def test_finds_multiple(self, tmp_path):
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
        genes = scan_skills(root=tmp_path, glob="*.md")
        assert len(genes) == 2

    def test_respects_glob(self, tmp_path):
        (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("# B\n", encoding="utf-8")
        genes = scan_skills(root=tmp_path, glob="*.md")
        assert len(genes) == 1
        assert genes[0].name == "a"


class TestSkillGenesToPool:
    def test_conversion(self):
        gene = SkillGene(
            gene_id="g1",
            name="test",
            intent="test intent",
            trigger_phrases=[],
            signal_keywords=["kw"],
            source_path="/tmp/test.md",
        )
        pool = skill_genes_to_selector_pool([gene])
        assert len(pool) == 1
        assert pool[0]["gene_id"] == "g1"
