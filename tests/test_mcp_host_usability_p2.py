"""P2 MCP host usability: honest project binding and structured error envelope."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from mcp_types import CallToolRequestParams


def _init_git_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("pin\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def _track_env(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    if key not in os.environ:
        monkeypatch.setenv(key, "")
    monkeypatch.delenv(key, raising=False)


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    for key in (
        "EVOLVER_NO_PARENT_GIT",
        "EVOLVER_REPO_ROOT",
        "EVOLVER_PROJECT_DIR",
        "OPENCLAW_WORKSPACE",
        "WORKSPACE_DIR",
    ):
        _track_env(monkeypatch, key)


def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    params = CallToolRequestParams(name=name, arguments=arguments)
    return asyncio.run(server._handle_call_tool(None, params))


class TestProjectBindingHonesty:
    def test_subdir_keeps_repo_root_and_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import evolve_status

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")
        sub = repo / "pkg"
        sub.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        st = evolve_status(project=str(sub))
        bound = st["bound_paths"]

        assert st["ok"] is True
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == sub.resolve()
        assert Path(bound["code_root"]).resolve() == repo.resolve()
        assert bound["differ"] is True
        assert bound["project_applied"] is True
        assert bound["warning"]

    def test_free_text_label_does_not_invent_a_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import evolve_status

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
        monkeypatch.chdir(tmp_path)

        st = evolve_status(project="just-a-label")
        bound = st["bound_paths"]

        assert st["ok"] is True
        assert os.environ["EVOLVER_REPO_ROOT"] == str(repo)
        assert os.environ["OPENCLAW_WORKSPACE"] == str(repo)
        assert not (tmp_path / "just-a-label").exists()
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == repo.resolve()
        assert bound["differ"] is False
        assert bound["project_applied"] is False
        assert bound["project_reason"] == "not_a_directory"
        assert bound["warning"]

    def test_git_root_project_has_no_mismatch_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_host_round

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")

        result = asyncio.run(swarm_host_round(agent_name="host", project=str(repo)))
        bound = result["bound_paths"]

        assert result["ok"] is True
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == repo.resolve()
        assert bound["differ"] is False
        assert bound["project_applied"] is True
        assert "warning" not in bound


class TestToolErrorEnvelope:
    def test_episode_get_missing_is_structured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.mcp_server import build_server

        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
        result = _call(build_server(), "episode_get", {"episode_id": "sha256:nope"})
        body = result.structured_content

        assert result.is_error is True
        assert body["ok"] is False
        assert body["error"] == "not_found"
        assert body["tool"] == "episode_get"
        assert "episode not found" in body["message"]
        assert isinstance(body["next_steps"], list) and body["next_steps"]
        echoed = json.loads(result.content[0].text)
        assert echoed["ok"] is False
        assert echoed["error"] == "not_found"
        assert not result.content[0].text.startswith("Error executing tool")

    def test_invalid_enum_and_asset_get_share_the_envelope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.solidify import write_state_for_solidify
        from evolver.mcp_server import build_server

        _isolate(tmp_path, monkeypatch)
        write_state_for_solidify({"run_id": "run_enum_check", "signals": []})
        server = build_server()
        enum_result = _call(server, "evolve_settle", {"validation_scope": "bogus"})
        enum_body = enum_result.structured_content
        assert enum_result.is_error is True
        assert enum_body["ok"] is False
        assert enum_body["error"] == "invalid_arguments"
        assert enum_body["tool"] == "evolve_settle"
        assert enum_body["message"]
        assert enum_body["next_steps"]

        missing = _call(server, "tool_asset_get", {"asset_id": "no-such-asset"})
        missing_body = missing.structured_content
        assert missing_body["ok"] is False
        assert missing_body["error"] == "not_found"
        assert missing_body["tool"] == "tool_asset_get"
        assert missing_body["next_steps"]

    def test_recorded_episode_stays_the_success_body(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep import episode_record
        from evolver.mcp_server import build_server

        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
        body = episode_record.build_episode(
            {
                "event": {
                    "type": "EvolutionEvent",
                    "id": "evt_p2",
                    "run_id": "run_p2",
                    "timestamp": "2026-11-01T00:00:00.000Z",
                    "gene_id": "gene_a",
                    "mutation": {"id": "mut_1", "category": "repair"},
                    "diff_snapshot": "+x",
                    "outcome": {"status": "success", "score": 1.0},
                },
                "validation_result": {"ok": True, "results": []},
                "fitness_verdict": None,
                "gate": {"accepted": True},
            }
        )
        stored = episode_record.record_episode(body)
        result = _call(build_server(), "episode_get", {"episode_id": stored["id"]})
        assert result.is_error is False
        assert result.structured_content["run_id"] == "run_p2"
        assert result.structured_content.get("ok") is not False

    def test_domain_failure_dict_is_not_rewrapped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.mcp_server import build_server

        _isolate(tmp_path, monkeypatch)
        result = _call(
            build_server(),
            "evolve_begin",
            {"hypothesis": "", "auto_discover": False},
        )
        body = result.structured_content

        assert result.is_error is False
        assert body["ok"] is False
        assert body["error"] == "empty_hypothesis"
        assert "tool" not in body
