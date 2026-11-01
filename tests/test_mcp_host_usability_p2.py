"""P2 MCP host usability: honest project binding and one error envelope.

``swarm_boot(project=...)`` must not hide a ``workspace_root != repo_root``
split, and a free-text label must not invent a workspace. Tool exceptions
that the MCP SDK used to stringify as ``Error executing tool ...`` return
``{ok: false, error, message, next_steps}``. Soft-accept dicts that already
use that shape stay as the tool returned them.
"""

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
    """Remember ``key`` so a later ``os.environ`` write is undone.

    ``monkeypatch.delenv`` records nothing when the key is already absent, so
    ``swarm_boot`` assigning it would leak into the next test.
    """
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
        from evolver.swarm import swarm_boot, swarm_status

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")
        sub = repo / "pkg"
        sub.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        boot = swarm_boot("host", project=str(sub))
        bound = boot["bound_paths"]

        assert boot["ok"] is True
        assert boot.get("error") is None
        assert boot["next_action"] != "stop_and_report"
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == sub.resolve()
        assert Path(bound["code_root"]).resolve() == repo.resolve()
        assert bound["differ"] is True
        assert bound["project_applied"] is True
        assert "repo_root" in bound["semantics"]
        assert "workspace_root" in bound["semantics"]
        assert "soft-continue" in bound["semantics"]
        assert bound["warning"]
        assert bound["next_steps"]
        assert any("workspace_root" in str(item) for item in boot.get("warnings") or [])
        assert boot.get("severity") == "soft"

        status = swarm_status()
        assert status["bound_paths"]["differ"] is True
        assert status["ok"] is True
        assert status.get("error") is None

    def test_free_text_label_does_not_invent_a_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_boot

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
        monkeypatch.chdir(tmp_path)

        boot = swarm_boot("host", project="just-a-label")
        bound = boot["bound_paths"]

        assert boot["ok"] is True
        assert boot.get("error") is None
        assert os.environ["EVOLVER_REPO_ROOT"] == str(repo)
        assert os.environ["OPENCLAW_WORKSPACE"] == str(repo)
        assert not (tmp_path / "just-a-label").exists()
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == repo.resolve()
        assert bound["differ"] is False
        assert bound["project_applied"] is False
        assert bound["project_reason"] == "not_a_directory"
        assert bound["warning"]
        assert bound["next_steps"]
        assert boot["next_action"] != "stop_and_report"

    def test_git_root_project_has_no_mismatch_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.supervision import set_state
        from evolver.swarm import swarm_host_round

        _isolate(tmp_path, monkeypatch)
        repo = _init_git_repo(tmp_path / "repo")
        set_state(True, by="test", reason="skip tick")

        result = asyncio.run(swarm_host_round(agent_name="host", project=str(repo)))
        bound = result["bound_paths"]

        assert result["ok"] is True
        assert Path(bound["repo_root"]).resolve() == repo.resolve()
        assert Path(bound["workspace_root"]).resolve() == repo.resolve()
        assert bound["differ"] is False
        assert bound["project_applied"] is True
        assert "warning" not in bound
        assert "semantics" in bound


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

    def test_invalid_enum_and_asset_get_share_the_envelope(self) -> None:
        from evolver.mcp_server import build_server

        server = build_server()
        enum_result = _call(server, "swarm_hook_event", {"event": "bogus"})
        enum_body = enum_result.structured_content
        assert enum_result.is_error is True
        assert enum_body["ok"] is False
        assert enum_body["error"] == "invalid_arguments"
        assert enum_body["tool"] == "swarm_hook_event"
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

    def test_soft_failure_dict_is_not_rewrapped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.mcp_server import build_server

        _isolate(tmp_path, monkeypatch)
        result = _call(build_server(), "swarm_hypothesis", {"hypothesis": {}})
        body = result.structured_content

        assert result.is_error is False
        assert body["ok"] is False
        assert body["error"] == "hypothesis_rejected"
        assert "tool" not in body
        assert body["failure_mode"]["retryable"] is True
