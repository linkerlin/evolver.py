"""WORKING_SESSION.md quota and boundary unlink."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.evolution_session import EvolutionSession
from evolver.gep.working_memory import (
    MAX_WORKING_CHARS,
    archive_and_clear,
    read_working,
    working_path,
    write_working,
)


def test_write_read_and_quota(temp_workspace: Path) -> None:
    written = write_working("ruled out the rename\n")
    assert written["source"] == "host_working"
    assert "ruled out" in read_working()
    with pytest.raises(ValueError, match="empty_working"):
        write_working("   ")
    with pytest.raises(ValueError, match="working_over_quota"):
        write_working("x" * (MAX_WORKING_CHARS + 1))


def test_archive_unlinks_the_live_file(temp_workspace: Path) -> None:
    write_working("scratch from the last level\n")
    result = archive_and_clear("accept")
    assert result["cleared"] is True
    assert result["archived"] is not None
    assert not working_path().exists()
    assert Path(result["archived"]).read_text(encoding="utf-8").startswith("scratch")
    assert archive_and_clear("accept")["cleared"] is False


def test_session_boundaries_clear_scratch(temp_workspace: Path) -> None:
    write_working("stale map\n")
    session = EvolutionSession()
    session.start_run("parent-snapshot-aaa")
    assert not working_path().exists()

    write_working("this round's dead end\n")
    session.begin_round("h", "cand-1")
    session.accept(gate=lambda run: {"accept": True})
    assert not working_path().exists()
    assert list((temp_workspace / "memory" / "evolution" / "working_archive").glob("accept_*.md"))


def test_incomplete_clears_scratch(temp_workspace: Path) -> None:
    session = EvolutionSession()
    session.start_run("parent-snapshot-aaa")
    write_working("stop here\n")
    session.mark_incomplete("user_interrupted")
    assert not working_path().exists()
