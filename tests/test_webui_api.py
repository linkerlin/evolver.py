"""Tests for evolver.webui.server.routes REST API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evolver.webui.app import app

client = TestClient(app)


class TestApiStatus:
    def test_status(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data


class TestApiAssets:
    def test_assets_empty(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        resp = client.get("/api/assets")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_assets_query(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "genes.json").write_text('{"genes":[{"id":"g1","summary":"hello world"}]}', encoding="utf-8")
        resp = client.get("/api/assets?q=hello")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_asset_detail(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "load_genes", lambda: [{"id": "g1", "summary": "x"}])
        monkeypatch.setattr(routes_mod, "load_capsules", lambda: [])
        resp = client.get("/api/assets/g1")
        assert resp.status_code == 200
        assert resp.json()["type"] == "gene"

    def test_asset_detail_404(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "load_genes", lambda: [])
        monkeypatch.setattr(routes_mod, "load_capsules", lambda: [])
        resp = client.get("/api/assets/nope")
        assert resp.status_code == 404


class TestApiCandidates:
    def test_candidates(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "load_genes", lambda: [{"id": "g1", "solidified": False}])
        resp = client.get("/api/candidates")
        assert resp.status_code == 200
        assert len(resp.json()["candidates"]) == 1


class TestApiCalls:
    def test_calls(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "read_all_events", lambda: [{"type": "invoke", "id": "c1"}])
        resp = client.get("/api/calls")
        assert resp.status_code == 200
        assert len(resp.json()["calls"]) == 1


class TestApiLineage:
    def test_lineage(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "load_genes", lambda: [{"id": "g1", "summary": "x"}])
        monkeypatch.setattr(routes_mod, "load_capsules", lambda: [{"id": "c1", "gene_id": "g1"}])
        monkeypatch.setattr(routes_mod, "read_all_events", lambda: [])
        resp = client.get("/api/lineage?gene_id=g1")
        assert resp.status_code == 200
        assert len(resp.json()["lineage"]) == 2


class TestApiPersonality:
    def test_personality(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        resp = client.get("/api/personality")
        assert resp.status_code == 200
        assert "dimensions" in resp.json()


class TestApiSkills:
    def test_skills(self, monkeypatch, tmp_path):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "s1").mkdir()
        (skill_dir / "s1" / "SKILL.md").write_text("# S1", encoding="utf-8")

        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "skills_status", lambda: {"total": 1, "skills": [{"id": "s1"}]})
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestApiSafety:
    def test_safety(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "events.jsonl").write_text('{"type":"policy_violation","severity":"high"}\n', encoding="utf-8")
        resp = client.get("/api/safety")
        assert resp.status_code == 200
        assert resp.json()["severity_counts"]["high"] == 1


class TestApiRuns:
    def test_runs(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "events.jsonl").write_text('{"type":"cycle_end","outcome":"success"}\n', encoding="utf-8")
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json()["total_cycles"] == 1


class TestApiPipelines:
    def test_pipelines(self, monkeypatch, tmp_path):
        import evolver.gep.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path)
        (tmp_path / "events.jsonl").write_text('{"type":"pipeline_start"}\n', encoding="utf-8")
        resp = client.get("/api/pipelines")
        assert resp.status_code == 200
        assert len(resp.json()["timeline"]) == 1


class TestApiLogs:
    def test_logs_sse(self, monkeypatch, tmp_path):
        import evolver.webui.server.routes as routes_mod
        monkeypatch.setattr(routes_mod, "read_all_events", lambda: [{"id": 1}])
        resp = client.get("/api/logs", headers={"x-test-mode": "1"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
