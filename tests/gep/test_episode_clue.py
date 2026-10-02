"""Tests for evolver.gep.episode_clue (经验即证据 §5.2).

The clue layer holds host-reported material, kept apart from the episode
record: append-only, source-tagged, bounded, and never merged into the
evidence block in the prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import episode_clue


@pytest.fixture
def episode_env(temp_workspace: Path) -> Path:
    return temp_workspace


def test_append_and_read_round_trip(episode_env: Path) -> None:
    episode_clue.append_clue("I searched the logs and found the retry loop")
    clues = episode_clue.recent_clues()
    assert len(clues) == 1
    assert clues[0]["source"] == "host_distill"
    assert "retry loop" in clues[0]["text"]


def test_recent_clues_returns_oldest_first_and_bounds(episode_env: Path) -> None:
    for i in range(8):
        episode_clue.append_clue(f"clue {i}")
    clues = episode_clue.recent_clues()
    assert [c["text"] for c in clues] == [f"clue {i}" for i in range(3, 8)]


def test_render_clue_block_tags_each_clue_in_order(episode_env: Path) -> None:
    episode_clue.append_clue("first account")
    episode_clue.append_clue("second account")
    block = episode_clue.render_clue_block(episode_clue.recent_clues())
    assert "leads, not evidence" in block
    assert block.index("[host_distill] first account") < block.index(
        "[host_distill] second account"
    )


def test_render_clue_block_truncates_past_the_budget(episode_env: Path) -> None:
    episode_clue.append_clue("x" * 5000)
    block = episode_clue.render_clue_block(episode_clue.recent_clues(), max_chars=200)
    assert len(block) <= 200 + len("\n... (truncated)")
    assert "truncated" in block


def test_empty_clue_store_renders_header_only(episode_env: Path) -> None:
    assert episode_clue.recent_clues() == []
    assert "Host Clues" in episode_clue.render_clue_block([])
