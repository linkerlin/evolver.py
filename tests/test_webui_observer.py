"""Tests for evolver.webui.observer modules."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer import (
    personality_data,
    redact_text,
    runs_history,
    safety_events,
    sanitize_path,
    serialize_assets,
    skills_status,
    stream_jsonl,
    system_status,
)


class TestStreamJsonl:
    def test_basic(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text('{"id":1}\n{"id":2}\n\n{"id":3}\n', encoding="utf-8")
        items = list(stream_jsonl(p))
        assert len(items) == 3
        assert items[0]["id"] == 1

    def test_limit(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text("\n".join(f'{{"id":{i}}}' for i in range(5)), encoding="utf-8")
        items = list(stream_jsonl(p, limit=2))
        assert len(items) == 2

    def test_since(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text('{"timestamp":1}\n{"timestamp":10}\n', encoding="utf-8")
        items = list(stream_jsonl(p, since=5))
        assert len(items) == 1
        assert items[0]["timestamp"] == 10

    def test_missing(self, tmp_path):
        assert list(stream_jsonl(tmp_path / "no.jsonl")) == []

    def test_malformed(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text('{"id":1}\nbad\n{"id":2}\n', encoding="utf-8")
        items = list(stream_jsonl(p))
        assert len(items) == 2


class TestSanitizePath:
    def test_relative_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "src" / "main.py"
        assert sanitize_path(sub) == "src/main.py"

    def test_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        p = tmp_path / "secret.txt"
        assert sanitize_path(p).startswith("~")

    def test_unrelated(self, tmp_path):
        p = tmp_path / "foo.txt"
        assert sanitize_path(p) == "foo.txt"


class TestRedact:
    def test_bearer(self):
        assert "<REDACTED>" in redact_text("Authorization: Bearer abc123xyz7890123456789")

    def test_api_key(self):
        assert "<REDACTED>" in redact_text("API_KEY=supersecret1234567890")

    def test_sk_token(self):
        assert "<REDACTED>" in redact_text("sk-abcdefghijklmnopqrstuvwxyz")

    def test_password(self):
        assert "<REDACTED>" in redact_text("password=hunter2")


class TestSerializeAssets:
    def test_empty(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_gep_assets_dir", lambda: tmp_path)
        result = serialize_assets()
        assert result["total"] == 0
        assert result["items"] == []

    def test_genes(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_gep_assets_dir", lambda: tmp_path)
        (tmp_path / "genes.json").write_text(
            '{"genes":[{"id":"g1","summary":"x"}]}', encoding="utf-8"
        )
        result = serialize_assets(type_filter="gene")
        assert result["total"] == 1
        assert result["items"][0]["id"] == "g1"

    def test_query(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_gep_assets_dir", lambda: tmp_path)
        (tmp_path / "genes.json").write_text(
            '{"genes":[{"id":"alpha","summary":"hello"}]}', encoding="utf-8"
        )
        result = serialize_assets(query="alp")
        assert result["total"] == 1

    def test_pagination(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_gep_assets_dir", lambda: tmp_path)
        genes = [{"id": f"g{i}"} for i in range(10)]
        (tmp_path / "genes.json").write_text(json.dumps({"genes": genes}), encoding="utf-8")
        result = serialize_assets(page=2, limit=3)
        assert len(result["items"]) == 3
        assert result["page"] == 2


class TestSystemStatus:
    def test_basic(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        result = system_status()
        assert "timestamp" in result
        assert "overall" in result


class TestPersonalityData:
    def test_missing(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        result = personality_data()
        assert result["dimensions"]["risk_tolerance"] == 0.5

    def test_existing(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "personality.json").write_text('{"risk_tolerance":0.9}', encoding="utf-8")
        result = personality_data()
        assert result["dimensions"]["risk_tolerance"] == 0.9


class TestSkillsStatus:
    def test_empty(self, tmp_path):
        result = skills_status(skills_dir=tmp_path)
        assert result["total"] == 0

    def test_with_skill(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill", encoding="utf-8")
        result = skills_status(skills_dir=tmp_path)
        assert result["total"] == 1
        assert result["skills"][0]["id"] == "my-skill"


class TestSafetyEvents:
    def test_empty(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        result = safety_events()
        assert result["total"] == 0

    def test_policy_violation(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "events.jsonl").write_text(
            '{"type":"policy_violation","severity":"high"}\n', encoding="utf-8"
        )
        result = safety_events()
        assert result["total"] == 1
        assert result["severity_counts"]["high"] == 1


class TestRunsHistory:
    def test_empty(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        result = runs_history()
        assert result["total_cycles"] == 0
        assert result["success_rate"] == 0.0

    def test_mixed(self, tmp_path, monkeypatch):
        import evolver.gep.paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        lines = [
            '{"type":"cycle_end","outcome":"success"}',
            '{"type":"cycle_end","outcome":"failure"}',
            '{"type":"cycle_end","outcome":"success"}',
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")
        result = runs_history()
        assert result["total_cycles"] == 3
        assert result["successes"] == 2
        assert round(result["success_rate"], 2) == 0.67
