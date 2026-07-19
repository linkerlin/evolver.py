"""Sprint 15.6 — sessionEndHook contracts (Python port of sessionEndHook.test.js)."""

from __future__ import annotations

import io
import json
import sys
import subprocess
from pathlib import Path

import pytest

from evolver.adapters.scripts import session_end as se


def _init_repo_with_diff(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\nworld\n", encoding="utf-8")


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("EVOLVER_HOOK_LOG_DIR", str(home / "logs"))
    monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
    monkeypatch.delenv("CURSOR_SESSION_ID", raising=False)
    monkeypatch.delenv("EVOLVER_HOOK_HOST", raising=False)
    monkeypatch.delenv("EVOLVER_HOOK_VERBOSE", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "xterm")
    return home


class TestCursorSuppression:
    def test_emits_system_message_on_non_cursor(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.chdir(repo)
        out = se.build_session_end_output()
        assert isinstance(out.get("systemMessage"), str)
        assert "[Evolution]" in out["systemMessage"]
        assert "followup_message" not in out
        log = (isolated_home / "logs" / "evolution.log").read_text(encoding="utf-8")
        assert "Evolution" in log

    def test_suppresses_when_term_program_cursor(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "cursor")
        monkeypatch.chdir(repo)
        assert se.build_session_end_output() == {}
        assert (isolated_home / "logs" / "evolution.log").exists()

    def test_suppresses_when_cursor_trace_id(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_home
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.setenv("CURSOR_TRACE_ID", "abc-123")
        monkeypatch.chdir(repo)
        assert se.build_session_end_output() == {}

    def test_verbose_escape_hatch(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_home
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "cursor")
        monkeypatch.setenv("EVOLVER_HOOK_VERBOSE", "1")
        monkeypatch.chdir(repo)
        out = se.build_session_end_output()
        assert isinstance(out.get("systemMessage"), str)

    def test_hook_host_override(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_home
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.setenv("EVOLVER_HOOK_HOST", "cursor")
        monkeypatch.chdir(repo)
        assert se.build_session_end_output() == {}


class TestProjectDirResolution:
    def test_cursor_project_dir_from_elsewhere(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_home
        repo = tmp_path / "repo"
        elsewhere = tmp_path / "elsewhere"
        repo.mkdir()
        elsewhere.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.chdir(elsewhere)
        out = se.build_session_end_output()
        assert isinstance(out.get("systemMessage"), str)
        assert "file" in out["systemMessage"].lower() or "change" in out["systemMessage"].lower()

    def test_claude_project_dir_alias(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = isolated_home
        repo = tmp_path / "repo"
        elsewhere = tmp_path / "elsewhere"
        repo.mkdir()
        elsewhere.mkdir()
        _init_repo_with_diff(repo)
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.chdir(elsewhere)
        out = se.build_session_end_output()
        assert isinstance(out.get("systemMessage"), str)


class TestNoChangesBreadcrumb:
    def test_non_git_workspace(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(nongit))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.chdir(nongit)
        assert se.build_session_end_output() == {}
        log = (isolated_home / "logs" / "evolution.log").read_text(encoding="utf-8")
        assert "nothing recorded (not a git workspace)" in log

    def test_clean_git_repo(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
        (repo / "a.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.chdir(repo)
        assert se.build_session_end_output() == {}
        log = (isolated_home / "logs" / "evolution.log").read_text(encoding="utf-8")
        assert "nothing recorded (no changes detected this session)" in log


class TestCwdTagConsistency:
    def test_tags_entry_cwd_with_project_dir(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        elsewhere = tmp_path / "elsewhere"
        repo.mkdir()
        elsewhere.mkdir()
        _init_repo_with_diff(repo)
        graph = isolated_home / ".evolver" / "memory" / "evolution" / "memory_graph.jsonl"
        graph.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(graph))
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo))
        monkeypatch.setenv("TERM_PROGRAM", "cursor")
        monkeypatch.chdir(elsewhere)
        assert se.build_session_end_output() == {}
        assert graph.exists()
        last = graph.read_text(encoding="utf-8").strip().splitlines()[-1]
        entry = json.loads(last)
        assert entry["cwd"] == str(repo)
        assert entry["cwd"] != str(elsewhere)


class TestIsCursorHost:
    def test_verbose_disables_detection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TERM_PROGRAM", "cursor")
        monkeypatch.setenv("EVOLVER_HOOK_VERBOSE", "1")
        assert se.is_cursor_host() is False

    def test_term_program(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOLVER_HOOK_VERBOSE", raising=False)
        monkeypatch.setenv("TERM_PROGRAM", "cursor")
        monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
        monkeypatch.delenv("CURSOR_SESSION_ID", raising=False)
        monkeypatch.delenv("EVOLVER_HOOK_HOST", raising=False)
        assert se.is_cursor_host() is True


# ---------------------------------------------------------------------------
# main() integration — stdin parsing + cwd extraction
# ---------------------------------------------------------------------------


class TestMainStdin:
    def test_main_with_stdin_no_crash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
        monkeypatch.delenv("EVOLVER_HOOK_VERBOSE", raising=False)
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))

        payload = json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": str(tmp_path), "agent": "codex"},
            }
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

        # Verify main() runs without raising.
        try:
            se.main()
        except Exception:
            pytest.fail("main() raised unexpectedly")

    def test_main_empty_stdin_no_crash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("EVOLVER_HOOK_VERBOSE", raising=False)
        monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))

        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

        try:
            se.main()
        except Exception:
            pytest.fail("main() raised unexpectedly on empty stdin")

    def test_main_malformed_stdin_no_crash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("EVOLVER_HOOK_VERBOSE", raising=False)
        monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))

        monkeypatch.setattr(sys, "stdin", io.StringIO("not valid {{{"))

        try:
            se.main()
        except Exception:
            pytest.fail("main() raised unexpectedly on malformed stdin")
