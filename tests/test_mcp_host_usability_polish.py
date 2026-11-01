"""Post-#12 MCP polish: approvals list envelope and short-tick log size.

These assertions fail while ``swarm_approvals`` returns a bare
``{pending, recent}`` object, and while ``prompt_mode=short`` still copies
the GEP gene preview into ``engine_log``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

_ENVELOPE_KEYS = frozenset({"ok", "items", "hint"})
_GEP_BANNER = "GENOME EVOLUTION PROTOCOL"


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point swarm state at tmp_path so a tick cannot touch the real tree."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    monkeypatch.setattr("evolver.config.SWARM_GATE_HANDOFF", "hotl")
    return tmp_path


def _tool_payload(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None) or []
    if not content:
        pytest.fail(f"tool returned an empty payload: {result!r}")
    text = content[0].text
    if not str(text).strip():
        pytest.fail("tool returned a blank body")
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


def _gep_embedded(log: str) -> bool:
    """True when captured stdout still carries the gene-preview text.

    Bridge mode JSON-escapes newlines inside ``sessions_spawn``; the banner
    stays readable either way.
    """
    plain = log.replace("\\n", "\n")
    return _GEP_BANNER in plain


class TestApprovalsEnvelope:
    def test_empty_approvals_use_the_list_envelope(self, isolated_swarm_env: Path) -> None:
        from evolver.mcp_server import build_server

        server = build_server()
        payload = _tool_payload(asyncio.run(server.call_tool("swarm_approvals", {})))

        assert payload["ok"] is True
        assert payload["items"] == []
        assert isinstance(payload["hint"], str) and payload["hint"].strip()
        assert set(payload) >= _ENVELOPE_KEYS
        assert payload["pending"] == []
        assert payload["recent"] == []
        assert "semantics" in payload

    def test_pending_rows_are_items_inside_the_same_envelope(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.hitl import request_approval
        from evolver.mcp_server import build_server

        monkeypatch.setattr("evolver.config.HITL_MODE", "on")
        created = request_approval(
            subject="solidify_skip_validation:run_polish",
            risk_reason="skip validation",
        )
        assert created["status"] == "pending"

        server = build_server()
        payload = _tool_payload(asyncio.run(server.call_tool("swarm_approvals", {})))

        assert payload["ok"] is True
        assert payload["items"] == payload["pending"]
        assert any(
            item.get("subject") == "solidify_skip_validation:run_polish"
            for item in payload["items"]
        )
        assert payload["recent"]
        assert "1 pending" in payload["hint"]
        assert "semantics" in payload and payload["semantics"].strip()


class TestShortTickLog:
    async def test_short_mode_drops_the_gep_blob_from_engine_log(
        self, isolated_swarm_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick(prompt_mode="short")
        assert result["ok"] is True
        assert result["prompt_mode"] == "short"
        shown = result.get("dispatch_prompt") or ""
        assert _GEP_BANNER not in shown
        log = str(result.get("engine_log") or "")
        artifact = Path(str(result["dispatch_prompt_artifact"])).read_text(encoding="utf-8")
        assert _GEP_BANNER in artifact
        assert not _gep_embedded(log)
        assert len(log) < 3000
        assert len(artifact) > len(log)
        assert "evolver://dispatch/last" in log or "omitted" in log
        assert "cycle phases:" in log

        # Without the OpenClaw bridge the engine prints BUILT_PROMPT + the
        # gene preview. Short mode drops that blob too.
        monkeypatch.setenv("EVOLVE_BRIDGE", "false")
        plain = await swarm_tick(prompt_mode="short")
        plain_log = str(plain.get("engine_log") or "")
        assert plain["prompt_mode"] == "short"
        assert not _gep_embedded(plain_log)
        assert "BUILT_PROMPT" not in plain_log
        assert len(plain_log) < 3000

    async def test_full_mode_still_exposes_the_log_and_prompt(
        self, isolated_swarm_env: Path
    ) -> None:
        from evolver.swarm import swarm_tick

        result = await swarm_tick()
        assert result["prompt_mode"] == "full"
        assert _GEP_BANNER in (result.get("dispatch_prompt") or "")
        assert _gep_embedded(str(result.get("engine_log") or ""))
        assert "gene_preview_omitted" not in result

    async def test_include_prompt_false_stays_full_and_keeps_the_log(
        self, isolated_swarm_env: Path
    ) -> None:
        from evolver.swarm import swarm_tick

        quiet = await swarm_tick(include_prompt=False)
        assert quiet["prompt_mode"] == "full"
        assert quiet["dispatch_prompt"] is None
        assert _gep_embedded(str(quiet.get("engine_log") or ""))

        quiet_short = await swarm_tick(include_prompt=False, prompt_mode="short")
        assert quiet_short["dispatch_prompt"] is None
        assert quiet_short["prompt_mode"] == "short"
        assert not _gep_embedded(str(quiet_short.get("engine_log") or ""))
