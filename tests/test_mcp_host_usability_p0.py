"""P0 MCP host usability: cold evolve_status, list envelopes, read-only doctor."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SOFT_GAPS = frozenset({"no_baseline", "pack_absent", "unmeasured"})
_ENVELOPE_KEYS = frozenset({"ok", "items", "hint"})


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _tool_payload(result: Any) -> Any:
    content = getattr(result, "content", None) or []
    if not content:
        pytest.fail(f"tool returned an empty payload: {result!r}")
    text = content[0].text
    if not str(text).strip():
        pytest.fail("tool returned a blank body")
    return json.loads(text)


def _isolate_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    return repo


class TestColdEvolveStatus:
    def test_cold_status_guides_host_to_evolve_begin_without_jargon(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import evolve_status

        _isolate_repo(tmp_path, monkeypatch)
        status = evolve_status()

        assert status["ok"] is True
        assert status["fsm_state"] == "IDLE"
        assert status["next_action"] == "evolve_begin"
        assert "evolve_begin" in status["hint"]
        assert status.get("error") not in _SOFT_GAPS
        assert "gate_soft_continue" not in status

    def test_preview_begin_stays_idle_and_does_not_mutate_pack(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.bench.frozen_gate import load_frozen_pack
        from evolver.swarm import evolve_begin, evolve_status

        _isolate_repo(tmp_path, monkeypatch)
        assert load_frozen_pack() is None

        preview = asyncio.run(evolve_begin(hypothesis="", auto_discover=True, agent_name="cold"))
        assert preview["ok"] is True
        assert preview["discovery_only"] is True
        assert preview["fsm_state"] == "IDLE"
        assert preview["next_action"] == "evolve_begin"

        status = evolve_status()
        assert status["fsm_state"] == "IDLE"
        assert load_frozen_pack() is None


class TestEmptyListEnvelope:
    def test_empty_search_and_timeline_are_objects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.mcp_server import build_server

        _isolate_repo(tmp_path, monkeypatch)
        server = build_server()
        cases = (
            ("tool_asset_search", {"query": "zzz_nonexistent_asset"}),
            ("tool_cycle_timeline", {"limit": 5}),
        )
        hints: list[str] = []
        for name, args in cases:
            payload = _tool_payload(asyncio.run(server.call_tool(name, args)))
            assert isinstance(payload, dict), name
            assert set(payload) == _ENVELOPE_KEYS, name
            assert payload["ok"] is True
            assert payload["items"] == []
            assert isinstance(payload["hint"], str) and payload["hint"].strip()
            hints.append(payload["hint"])
        assert len(set(hints)) == 2

    def test_search_hit_uses_the_same_envelope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.asset_store import upsert_gene
        from evolver.mcp_server import build_server

        _isolate_repo(tmp_path, monkeypatch)
        upsert_gene(
            {
                "type": "Gene",
                "id": "gene_fix_import",
                "name": "Fix missing import",
                "description": "Repair ImportError by adding the missing module import",
                "category": "repair",
            }
        )
        server = build_server()
        payload = _tool_payload(
            asyncio.run(server.call_tool("tool_asset_search", {"query": "import"}))
        )
        assert set(payload) == _ENVELOPE_KEYS
        assert payload["ok"] is True
        assert any(item["id"] == "gene_fix_import" for item in payload["items"])
        assert payload["hint"].strip()


class TestReadOnlyDoctor:
    def test_swarm_doctor_summarizes_without_mutating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.bench.frozen_gate import frozen_pack_path, load_frozen_pack
        from evolver.swarm import swarm_doctor

        _isolate_repo(tmp_path, monkeypatch)
        pack_path = frozen_pack_path()
        assert load_frozen_pack() is None
        assert not pack_path.exists()

        report = swarm_doctor()
        assert report["ok"] is True
        assert report["read_only"] is True
        assert report["soft_continue"] is True
        assert report["loop_ready"] is False
        assert report["blockers"] == []
        assert any(
            item["id"] == "freeze_pack" and item["severity"] == "soft" for item in report["checks"]
        )
        assert load_frozen_pack() is None
        assert not pack_path.exists()
