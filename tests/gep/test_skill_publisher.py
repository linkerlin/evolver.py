"""Tests for evolver.gep.skill_publisher."""

from unittest.mock import MagicMock, patch

import pytest

from evolver.gep.skill_distiller import DistilledSkill
from evolver.gep.skill_publisher import (
    SkillPublication,
    _load_published_hashes,
    _save_published_hashes,
    list_publishable_skills,
    publish_skill,
)


class TestPublishedHashes:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "published.json"
        hashes = {"abc", "def"}
        _save_published_hashes(hashes, path=path)
        loaded = _load_published_hashes(path=path)
        assert loaded == hashes

    def test_missing_file(self, tmp_path):
        path = tmp_path / "missing.json"
        assert _load_published_hashes(path=path) == set()


class TestPublishSkill:
    def test_feature_flag_off(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_PUBLISHING", "0")
        skill = DistilledSkill("s", "i", [], [], [], "hash1")
        assert publish_skill(skill) is None

    def test_deduplication(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_PUBLISHING", "1")
        dedup = tmp_path / "published.json"
        _save_published_hashes({"hash1"}, path=dedup)
        skill = DistilledSkill("s", "i", [], [], [], "hash1")
        assert publish_skill(skill, dedup_path=dedup) is None

    def test_publish_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_PUBLISHING", "1")
        dedup = tmp_path / "published.json"
        skill = DistilledSkill("s", "i", [], [], [], "hash2")
        mock_result = {"service_id": "skill-hash2"}
        result = publish_skill(skill, dedup_path=dedup, _publish_fn=lambda **kw: mock_result)
        assert result is not None
        assert result.skill_name == "s"
        assert result.source_hash == "hash2"
        assert "hash2" in _load_published_hashes(path=dedup)


class TestListPublishableSkills:
    def test_finds_unpublished(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_PUBLISHING", "1")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test.md").write_text("# Test\n\nIntent.\n", encoding="utf-8")
        unpublished = list_publishable_skills(skill_dir=skills_dir)
        assert len(unpublished) == 1
        assert unpublished[0].name == "test"

    def test_skips_published(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_PUBLISHING", "1")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test.md").write_text("# Test\n\nIntent.\n", encoding="utf-8")
        # Pre-publish
        dedup = tmp_path / "published.json"
        import hashlib
        text = (skills_dir / "test.md").read_text()
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        _save_published_hashes({h}, path=dedup)
        unpublished = list_publishable_skills(skill_dir=skills_dir, dedup_path=dedup)
        assert unpublished == []
