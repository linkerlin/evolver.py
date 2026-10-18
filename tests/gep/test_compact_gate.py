"""Compaction marker locks mutation tools until the scratch pad is written."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.adapters import claude_code
from evolver.gep.compact_gate import (
    REJECT_STREAK_BEFORE_CHECKPOINT,
    checkpoint_pending,
    note_outcome,
    pending_block,
    precompact_decision,
    request_checkpoint,
)
from evolver.gep.episode_record import build_episode, record_episode
from evolver.swarm import (
    swarm_checkpoint_working,
    swarm_distill,
    swarm_hook_event,
    swarm_tick,
)


def test_marker_refuses_distill_until_checkpoint(temp_workspace: Path) -> None:
    assert pending_block() is None
    request_checkpoint("test")
    refused = swarm_distill("not a gene")
    assert refused["error"] == "checkpoint_required"
    assert refused["next_action"] == "call_swarm_checkpoint_working"
    assert "steer_message" in refused

    saved = swarm_checkpoint_working("hypothesis still open; ruled out rename\n")
    assert saved["ok"] is True
    assert saved["checkpoint_cleared"] is True
    assert checkpoint_pending() is False
    assert swarm_distill("")["error"] == "empty_response"


def test_precompact_hook_sets_the_marker(temp_workspace: Path) -> None:
    result = swarm_hook_event("precompact")
    assert result["ok"] is True
    assert result["next_action"] == "call_swarm_checkpoint_working"
    assert checkpoint_pending() is True


def test_four_failures_request_a_checkpoint(temp_workspace: Path) -> None:
    for _ in range(REJECT_STREAK_BEFORE_CHECKPOINT - 1):
        note_outcome(False)
    assert checkpoint_pending() is False
    note_outcome(False)
    assert checkpoint_pending() is True
    note_outcome(True)
    # A later success resets the streak but does not clear a marker already set.
    assert checkpoint_pending() is True


def test_claude_precompact_hook_is_installed(tmp_path: Path) -> None:
    hooks = claude_code.build_hooks(tmp_path)
    assert "PreCompact" in hooks["hooks"]


def test_settled_run_returns_the_episode_without_resolidifying(temp_workspace: Path) -> None:
    from evolver.gep.paths import get_solidify_state_path
    from evolver.swarm import swarm_solidify

    scene = {
        "event": {
            "id": "evt_settled",
            "run_id": "run_settled",
            "timestamp": "2026-10-18T00:00:00.000Z",
            "gene_id": "gene_s",
            "mutation": {"id": "mut_s", "category": "repair"},
            "diff_snapshot": "+a\n",
            "outcome": {"status": "success", "score": 1.0},
        },
        "validation_result": {"ok": True, "results": []},
        "gate": {"accepted": True},
    }
    stored = record_episode(build_episode(scene))  # type: ignore[arg-type]
    path = get_solidify_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"last_run": {"run_id": "run_settled"}, "last_solidify": {"run_id": "run_settled"}}',
        encoding="utf-8",
    )
    result = swarm_solidify()
    assert result["status"] == "already_settled"
    assert result["episode_id"] == stored["id"]
    assert result["next_action"] == "swarm_tick"


def test_tick_is_refused_while_the_marker_is_set(temp_workspace: Path) -> None:
    request_checkpoint("test")
    import asyncio

    result = asyncio.run(swarm_tick())
    assert result["error"] == "checkpoint_required"


def test_boot_returns_the_full_scratch(temp_workspace: Path) -> None:
    from evolver.swarm import swarm_boot

    assert "working_session_text" not in swarm_boot("t")
    text = "ruled out: rename\n" + "y" * 1_000 + "\nkey episode: sha256:abc\n"
    swarm_checkpoint_working(text)
    booted = swarm_boot("t")
    assert booted["working_session_text"] == text
    assert booted["working_session_source"] == "host_working"


def test_precompact_blocks_once_then_lets_a_full_context_through(temp_workspace: Path) -> None:
    first = precompact_decision()
    assert first["decision"] == "block"
    assert "swarm_checkpoint_working" in first["reason"]
    assert checkpoint_pending() is True
    # The host ignored the block: never stall a full context, keep tools gated.
    assert precompact_decision() == {}
    assert checkpoint_pending() is True


def test_checkpoint_after_a_block_releases_the_next_compaction(temp_workspace: Path) -> None:
    assert precompact_decision()["decision"] == "block"
    swarm_checkpoint_working("state saved\n")
    assert precompact_decision() == {}
    # The release is spent; the next compaction asks again.
    assert precompact_decision()["decision"] == "block"


def test_streak_marker_still_blocks_compaction_until_written(temp_workspace: Path) -> None:
    request_checkpoint("reject_streak")
    assert precompact_decision()["decision"] == "block"
    swarm_checkpoint_working("state saved\n")
    assert precompact_decision() == {}


def test_hook_script_prints_the_decision(
    temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.adapters.scripts import compact_checkpoint

    assert compact_checkpoint.main() == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert compact_checkpoint.main() == 0
    assert json.loads(capsys.readouterr().out) == {}
