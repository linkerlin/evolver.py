"""Sprint 15.6 — sessionSourceDiagnostic contracts."""

from __future__ import annotations

from pathlib import Path

from evolver.evolve.pipeline.collect import (
    diagnose_session_source_empty,
    reset_session_source_warning,
)


def test_lists_available_openclaw_agents(tmp_path: Path) -> None:
    (tmp_path / ".openclaw" / "agents" / "coder" / "sessions").mkdir(parents=True)
    (tmp_path / ".openclaw" / "agents" / "worker-01" / "sessions").mkdir(parents=True)
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "sessionSource": "auto",
            "cursorTranscriptsDir": "",
        }
    )
    assert diag["agentSessionsDirExists"] is False
    assert sorted(diag["availableOpenClawAgents"]) == ["coder", "worker-01"]
    hint = "\n".join(diag["hints"])
    assert 'AGENT_NAME="main"' in hint
    assert "coder" in hint
    assert "worker-01" in hint


def test_no_sources_hint(tmp_path: Path) -> None:
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "sessionSource": "auto",
            "cursorTranscriptsDir": "",
        }
    )
    assert diag["agentSessionsDirExists"] is False
    assert diag["availableOpenClawAgents"] == []
    assert any("No session sources detected" in h for h in diag["hints"])


def test_openclaw_source_missing_dir(tmp_path: Path) -> None:
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "sessionSource": "openclaw",
            "cursorTranscriptsDir": "",
        }
    )
    hint = "\n".join(diag["hints"])
    assert "EVOLVER_SESSION_SOURCE=openclaw" in hint
    assert "does not exist" in hint


def test_cursor_source_missing_ide_dirs(tmp_path: Path) -> None:
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "sessionSource": "cursor",
            "cursorTranscriptsDir": "",
        }
    )
    hint = "\n".join(diag["hints"])
    assert "EVOLVER_SESSION_SOURCE=cursor" in hint
    assert "~/.cursor" in hint or ".cursor" in hint


def test_no_hints_when_agent_dir_exists(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".openclaw" / "agents" / "main" / "sessions"
    agent_dir.mkdir(parents=True)
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "agentSessionsDir": agent_dir,
            "sessionSource": "auto",
            "cursorTranscriptsDir": "",
        }
    )
    assert diag["agentSessionsDirExists"] is True
    assert diag["hints"] == []


def test_cursor_transcripts_override(tmp_path: Path) -> None:
    override = tmp_path / "cursor-override"
    override.mkdir()
    diag = diagnose_session_source_empty(
        {
            "homedir": tmp_path,
            "agentName": "main",
            "sessionSource": "cursor",
            "cursorTranscriptsDir": str(override),
        }
    )
    hint = "\n".join(diag["hints"])
    assert "EVOLVER_SESSION_SOURCE=cursor" not in hint


def test_reset_session_source_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    diag = reset_session_source_warning()
    assert "hints" in diag
