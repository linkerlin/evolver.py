"""P0 MCP host usability: cold status, list envelopes, read-only doctor.

These assertions describe the host-visible contract. They fail while
``swarm_status`` has no boot hint, list tools still return ``[]``, and
``swarm_doctor`` is absent.
"""

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


def _clear_session_claim() -> None:
    from evolver import swarm

    if hasattr(swarm, "_session_claim"):
        swarm._session_claim = None


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


class TestColdSwarmStatus:
    def test_unclaimed_status_tells_the_host_to_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_status

        _clear_session_claim()
        _isolate_repo(tmp_path, monkeypatch)
        status = swarm_status()

        assert status["ok"] is True
        assert status["session_claimed"] is False
        assert status["next_action"] == "swarm_boot"
        assert "swarm_boot" in status["hint"]
        assert status.get("agent_name") in (None, "")
        assert "source_revision" in status
        assert status.get("error") not in _SOFT_GAPS
        # Soft-continue stays available as data; the cold hint does not hard-stop.
        assert status.get("severity") != "hard"

    def test_status_after_boot_keeps_agent_revision_and_soft_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.bench.frozen_gate import load_frozen_pack
        from evolver.swarm import swarm_boot, swarm_status

        _clear_session_claim()
        _isolate_repo(tmp_path, monkeypatch)
        assert load_frozen_pack() is None

        boot = swarm_boot("cold-host")
        assert boot["ok"] is True
        assert boot["agent_name"] == "cold-host"
        assert boot["next_action"] == "swarm_tick"
        assert boot.get("error") not in _SOFT_GAPS
        assert boot.get("severity") == "soft"
        assert boot.get("gap") == "pack_absent"
        assert "tick_again" not in boot

        status = swarm_status()
        assert status["session_claimed"] is True
        assert status["agent_name"] == "cold-host"
        assert isinstance(status["source_revision"], str) and status["source_revision"]
        assert status["next_action"] == "swarm_tick"
        assert status.get("gap") == "pack_absent"
        assert status.get("severity") == "soft"
        assert status.get("gate_soft_continue") is True
        assert "tick_again" not in status
        assert status.get("warnings")
        assert status.get("error") not in _SOFT_GAPS
        assert status["ok"] is True
        # Boot did not install the pack; status must not grow a hard gate either.
        assert load_frozen_pack() is None


class TestEmptyListEnvelope:
    def test_empty_search_poll_and_timeline_are_objects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.mcp_server import build_server

        _isolate_repo(tmp_path, monkeypatch)
        server = build_server()
        cases = (
            ("tool_asset_search", {"query": "zzz_nonexistent_asset"}),
            ("tool_mailbox_poll", {"limit": 5, "direction": "inbound"}),
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
        # Same shape, but each tool explains its own empty result.
        assert len(set(hints)) == 3

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
        from evolver.swarm import build_instrument_prompt, swarm_doctor

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
        assert report.get("error") not in _SOFT_GAPS
        assert any(
            item["id"] == "freeze_pack" and item["severity"] == "soft" for item in report["checks"]
        )
        assert report["warnings"]
        assert all(item["severity"] == "soft" for item in report["warnings"])
        assert any(item.get("gap") == "pack_absent" for item in report["warnings"])
        fixes = " ".join(report["fixes"])
        assert "evolver doctor" in fixes or "evolver bench freeze" in fixes
        assert load_frozen_pack() is None
        assert not pack_path.exists()

        prompt = build_instrument_prompt({"agent_name": "a", "workspace_root": "/ws"})
        assert "swarm_doctor" in prompt

    def test_doctor_tool_is_read_only_and_has_no_fix_switch(self) -> None:
        from evolver.mcp_server import build_server

        server = build_server()
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        doctor = tools["swarm_doctor"]
        annotations = doctor.annotations
        read_only = (
            annotations.read_only_hint
            if annotations is not None and hasattr(annotations, "read_only_hint")
            else (annotations or {}).get("readOnlyHint")
        )
        assert read_only is True
        schema = doctor.input_schema
        raw = schema if isinstance(schema, dict) else schema.model_dump()
        props = raw.get("properties") or {}
        assert "fix" not in props
