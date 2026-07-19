"""Tests for evolver.evolve.utils — extract_transcript_cwd and session scope."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.evolve.utils import extract_transcript_cwd, resolve_session_scope


class TestExtractTranscriptCwd:
    """5 contract tests for extract_transcript_cwd."""

    def test_extracts_cwd_from_codex_meta(self):
        """Contract 1: extracts cwd from Codex session_meta record."""
        records = [
            {
                "type": "session_meta",
                "payload": {"cwd": "/home/user/project", "agent": "codex"},
            }
        ]
        result = extract_transcript_cwd(records)
        assert result == Path("/home/user/project")

    def test_empty_records_returns_none(self):
        """Contract 2: empty transcript returns None."""
        result = extract_transcript_cwd([])
        assert result is None

    def test_no_cwd_field_returns_none(self):
        """Contract 3: transcript without cwd field returns None."""
        records = [
            {"type": "interaction", "message": "Hello"},
            {"type": "solidify", "gene_id": "g-1"},
        ]
        result = extract_transcript_cwd(records)
        assert result is None

    def test_skips_malformed_jsonl(self, tmp_path: Path):
        """Contract 4: malformed JSONL file is skipped gracefully."""
        tmp = tmp_path / "transcript.jsonl"
        tmp.write_text(
            '{"type":"ok"}\nbadline\n{"type":"session_meta","payload":{"cwd":"/tmp/workspace"}}\n',
            encoding="utf-8",
        )
        result = extract_transcript_cwd(transcript_path=tmp)
        assert result == Path("/tmp/workspace")

    def test_direct_cwd_field_codex(self):
        """Contract 5a: extracts cwd from direct cwd field (Codex style)."""
        records = [{"cwd": "/workspace/app", "type": "interaction"}]
        result = extract_transcript_cwd(records)
        assert result == Path("/workspace/app")

    def test_direct_cwd_field_memory_graph(self):
        """Contract 5b: extracts cwd from direct cwd field (memory graph style)."""
        records = [
            {
                "project_dir": "/home/dev/repo",
                "type": "session",
                "agent": "claude-code",
            }
        ]
        result = extract_transcript_cwd(records)
        assert result == Path("/home/dev/repo")

    def test_from_file_path(self, tmp_path: Path):
        """Extracts cwd by reading a transcript file."""
        tmp = tmp_path / "transcript.jsonl"
        tmp.write_text(
            json.dumps({"type": "session_meta", "payload": {"cwd": "/tmp/workdir"}}) + "\n",
            encoding="utf-8",
        )
        result = extract_transcript_cwd(transcript_path=tmp)
        assert result == Path("/tmp/workdir")

    def test_missing_file(self):
        """Missing transcript file returns None."""
        result = extract_transcript_cwd(transcript_path="/nonexistent/path.jsonl")
        assert result is None


class TestResolveSessionScope:
    def test_with_cwd(self):
        scope = resolve_session_scope(cwd="/home/user/project")
        assert len(scope) == 16
        assert scope != "default"

    def test_with_cwd_and_agent(self):
        scope = resolve_session_scope(cwd="/home/user/project", agent_name="codex")
        assert len(scope) == 16

    def test_default(self):
        assert resolve_session_scope() == "default"

    def test_deterministic(self):
        a = resolve_session_scope(cwd="/a", agent_name="codex")
        b = resolve_session_scope(cwd="/a", agent_name="codex")
        assert a == b

    def test_different_inputs(self):
        a = resolve_session_scope(cwd="/a", agent_name="codex")
        b = resolve_session_scope(cwd="/b", agent_name="codex")
        assert a != b
