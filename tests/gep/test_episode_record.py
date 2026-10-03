"""Tests for evolver.gep.episode_record (经验即证据 §5.1).

The runtime holds the record of one self-improvement round and that record is
written once: the same content is idempotent, a second content for the same
round is refused, and only engine-side facts enter — host-reported material is
the clue layer and has its own channel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import episode_record
from evolver.gep.episode_record import EpisodeConflictError


@pytest.fixture
def episode_env(temp_workspace: Path) -> Path:
    return temp_workspace


def scene(diff: str = "--- a.py\n+++ b.py\n-x = 1\n+x = 2\n") -> dict[str, object]:
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": "evt_1_abc",
            "run_id": "run_1",
            "timestamp": "2026-10-02T00:00:00.000Z",
            "gene_id": "gene_a",
            "mutation": {"id": "mut_1", "category": "repair"},
            "diff_snapshot": diff,
            "outcome": {"status": "success", "score": 1.0},
            "blast_radius": {"files": 1, "lines": 4},
        },
        "validation_result": {
            "ok": True,
            "results": [
                {
                    "command": "uv run pytest",
                    "ok": True,
                    "duration_ms": 12,
                    "stdout": "1 passed",
                    "stderr": "",
                }
            ],
        },
        "fitness_verdict": None,
        "gate": {"accepted": True, "reason": "improved"},
    }


# ---------------------------------------------------------------------------
# Storage: content address, one write per round
# ---------------------------------------------------------------------------


def test_recorded_episode_is_readable_by_id(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    stored = episode_record.record_episode(body)
    assert stored["ok"] is True and stored["reason"] == "stored"
    assert episode_record.load_episode(stored["id"]) == body
    assert stored["id"] == episode_record.episode_id(body)


def test_same_content_twice_is_idempotent(episode_env: Path) -> None:
    first = episode_record.record_episode(episode_record.build_episode(scene()))
    second = episode_record.record_episode(episode_record.build_episode(scene()))
    assert second["reason"] == "already_stored"
    assert second["id"] == first["id"]
    assert len(episode_record.list_episodes()) == 1


def test_a_round_is_written_once_even_when_the_scene_changes(episode_env: Path) -> None:
    episode_record.record_episode(episode_record.build_episode(scene()))
    tampered = episode_record.build_episode(scene(diff="--- a.py\n+++ b.py\n-x = 1\n+x = 999\n"))
    with pytest.raises(EpisodeConflictError):
        episode_record.record_episode(tampered)
    assert len(episode_record.list_episodes()) == 1


def test_the_same_bytes_under_another_round_are_a_second_record(episode_env: Path) -> None:
    first = episode_record.record_episode(episode_record.build_episode(scene()))
    other = episode_record.build_episode(scene())
    other["run_id"] = "run_2"
    other["event_id"] = "evt_2_def"
    second = episode_record.record_episode(other)
    assert second["reason"] == "stored"
    assert second["id"] != first["id"]
    assert len(episode_record.list_episodes()) == 2


# ---------------------------------------------------------------------------
# Layering: engine-side only
# ---------------------------------------------------------------------------


def test_host_reported_material_is_refused(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    body["account"] = "I searched carefully and everything is fine"
    with pytest.raises(ValueError, match="host-reported"):
        episode_record.record_episode(body)


def test_unknown_fields_are_refused(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    body["mood"] = "confident"
    with pytest.raises(ValueError, match="unknown episode field"):
        episode_record.record_episode(body)


def test_host_material_in_the_scene_is_dropped_not_copied(episode_env: Path) -> None:
    messy = scene()
    messy_event = messy["event"]
    assert isinstance(messy_event, dict)
    messy_event["account"] = "the host says it worked"
    messy_event["tool_actions"] = [{"tool": "search"}]
    body = episode_record.build_episode(messy)
    assert "account" not in body
    assert "tool_actions" not in body
    assert "diff" in body and body["diff"].startswith("--- a.py")


def test_an_episode_without_an_identity_is_refused(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    body["run_id"] = ""
    body["event_id"] = ""
    with pytest.raises(ValueError, match="run_id or an event_id"):
        episode_record.record_episode(body)


# ---------------------------------------------------------------------------
# Bounded view
# ---------------------------------------------------------------------------


def test_build_episode_is_bounded(episode_env: Path) -> None:
    huge = scene(diff="x" * 50_000)
    huge_validation = huge["validation_result"]
    assert isinstance(huge_validation, dict)
    huge_validation["results"] = [
        {"command": "uv run pytest", "ok": False, "stdout": "y" * 50_000, "stderr": "z" * 50_000}
    ] * 50
    body = episode_record.build_episode(huge)
    assert len(body["diff"]) <= episode_record.MAX_DIFF_CHARS
    assert len(body["checks"]) <= episode_record.MAX_CHECKS
    for check in body["checks"]:
        assert len(check["stdout"]) <= episode_record.MAX_CHECK_OUTPUT_CHARS
        assert len(check["stderr"]) <= episode_record.MAX_CHECK_OUTPUT_CHARS


def test_an_oversized_record_is_refused_rather_than_silently_trimmed(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    body["gates"] = {"acceptance": {"blob": "g" * episode_record.MAX_RECORD_CHARS}}
    with pytest.raises(ValueError, match="exceeds"):
        episode_record.record_episode(body)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def test_index_lists_the_round_with_its_engine_side_summary(episode_env: Path) -> None:
    stored = episode_record.record_episode(episode_record.build_episode(scene()))
    entries = episode_record.list_episodes()
    assert [row["id"] for row in entries] == [stored["id"]]
    row = entries[0]
    assert row["run_id"] == "run_1"
    assert row["gene_id"] == "gene_a"
    assert row["outcome_status"] == "success"
    assert row["score"] == 1.0
    assert row["accepted"] is True


def test_a_corrupt_index_is_never_silently_restarted(episode_env: Path) -> None:
    episode_record.index_path().parent.mkdir(parents=True, exist_ok=True)
    episode_record.index_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(EpisodeConflictError, match="unreadable"):
        episode_record.load_index()


# ---------------------------------------------------------------------------
# Round entry: derived from the immutable scene
# ---------------------------------------------------------------------------


def test_record_round_finds_the_scene_by_event_id(episode_env: Path) -> None:
    from evolver.gep.evidence import save_evidence

    save_evidence("run_1", "evt_1_abc", scene())
    stored = episode_record.record_round(event_id="evt_1_abc")
    assert stored["ok"] is True
    body = episode_record.load_episode(stored["id"])
    assert body is not None
    assert body["run_id"] == "run_1"
    assert body["event_id"] == "evt_1_abc"


def test_record_round_is_idempotent_across_calls(episode_env: Path) -> None:
    from evolver.gep.evidence import save_evidence

    save_evidence("run_1", "evt_1_abc", scene())
    first = episode_record.record_round(event_id="evt_1_abc", run_id="run_1")
    second = episode_record.record_round(event_id="evt_1_abc", run_id="run_1")
    assert first["id"] == second["id"]
    assert second["reason"] == "already_stored"


def test_record_round_without_a_scene_reports_missing(episode_env: Path) -> None:
    result = episode_record.record_round(event_id="evt_missing")
    assert result == {"ok": False, "error": "scene_missing", "event_id": "evt_missing"}


# ---------------------------------------------------------------------------
# Call-graph pin (经验即证据 §4): the mutation path writes no record of itself
# ---------------------------------------------------------------------------


def test_the_record_writer_is_absent_from_the_mutation_call_graph() -> None:
    """The writer lives at the cycle boundary (CLI / MCP). The apply-mutation
    path, the cycle pipeline and the solve path must not reach it — a round's
    history is written by the runtime, never by the thing being scored.
    The pin scans for writer calls: ``record_episode(`` and ``append_clue(``
    are unique to this subsystem; ``record_round(`` is NOT scanned bare because
    ``EvolutionSession.record_round`` (the session ledger) shares the name —
    only the qualified ``episode_record.record_round(`` form is pinned. Readers
    are allowed — dispatch must read the last episode to render it."""
    repo = Path(__file__).resolve().parents[2]
    guarded = [
        repo / "src/evolver/gep/solidify.py",
        *sorted((repo / "src/evolver/evolve").rglob("*.py")),
        *sorted((repo / "src/evolver/bench").rglob("*.py")),
    ]
    assert guarded, "call-graph scan found no files"
    for name in ("record_episode(", "append_clue(", "episode_record.record_round("):
        for path in guarded:
            assert name not in path.read_text(encoding="utf-8"), (
                f"{path.name} references {name} — the episode record must be "
                "written at the cycle boundary, not by the mutation path"
            )


def test_the_record_writer_is_confined_to_a_declared_boundary() -> None:
    """The pin above guards three known paths; a new writer elsewhere would slip
    through. Scan all of ``src/`` and require every writer call site to be on an
    explicit allowlist — adding a writer entry point becomes a reviewed change."""
    repo = Path(__file__).resolve().parents[2]
    src = repo / "src" / "evolver"
    allowed = {
        "cli.py",
        "swarm.py",
        "gep/episode_record.py",
        "gep/episode_clue.py",
        "gep/record_route.py",
    }
    names = ("record_episode(", "append_clue(", "episode_record.record_round(")
    found: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in names):
            found.add(path.relative_to(src).as_posix())
    assert found, "scan found no writer call sites — the pin is blind"
    stray = found - allowed
    assert not stray, (
        f"episode writer referenced outside the declared boundary: {sorted(stray)} — "
        "add it to the allowlist only if it is a cycle-boundary entry point"
    )


def test_the_record_body_survives_a_json_round_trip(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    stored = episode_record.record_episode(body)
    on_disk = json.loads(episode_record.episode_path(stored["id"]).read_text(encoding="utf-8"))
    assert on_disk == body


# ---------------------------------------------------------------------------
# Render: the prompt-facing view
# ---------------------------------------------------------------------------


def test_render_episode_block_cites_the_id_and_summarizes(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    stored = episode_record.record_episode(body)
    block = episode_record.render_episode_block(body, ep_id=stored["id"])
    assert stored["id"] in block
    assert "gene_a" in block
    assert "success" in block
    assert "1/1 ok" in block
    assert "acceptance=True" in block


def test_render_episode_block_truncates_past_the_budget(episode_env: Path) -> None:
    body = episode_record.build_episode(scene())
    block = episode_record.render_episode_block(body, max_chars=120)
    assert len(block) <= 120 + len("\n... (truncated)")
    assert "truncated" in block


# ---------------------------------------------------------------------------
# Val seal (经验即证据 §5.3): a leak must not get a content address
# ---------------------------------------------------------------------------


def _arm_val_pack() -> None:
    from evolver.bench import frozen_gate

    tasks = [
        {
            "id": "val-seal-1",
            "split": "val",
            "title": "the sealed question wording is long enough to be strong",
            "prompt": "Write the quarterly reconciliation breakdown by ledger id.",
            "sandbox": {"rules.txt": "UNIQUE-VAL-ONLY-RULESET-42"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "reconciled:42|ledger"},
        },
    ]
    path = frozen_gate.frozen_pack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pack_version": 1, "tasks": tasks}, indent=2), encoding="utf-8")


def test_a_val_secret_in_the_diff_is_redacted_before_storage(episode_env: Path) -> None:
    _arm_val_pack()
    secret = "reconciled:42|ledger"
    body = episode_record.build_episode(scene(diff=f"--- a.py\n+++ b.py\n+x = '{secret}'\n"))
    stored = episode_record.record_episode(body)
    on_disk = episode_record.load_episode(stored["id"])
    assert on_disk is not None
    assert secret not in json.dumps(on_disk)
    assert "[sealed:val]" in json.dumps(on_disk)


def test_seal_targets_list_the_episode_record() -> None:
    from evolver.gep import val_seal

    assert "episode_record" in val_seal.SEAL_TARGETS


def test_record_round_attaches_gene_metadata(episode_env: Path) -> None:
    """经验即证据 §5.4: the record is self-contained — target_hook attached
    from the library so usage is recomputable from the record alone."""
    from evolver.gep.asset_store import upsert_gene
    from evolver.gep.evidence import save_evidence

    upsert_gene(
        {
            "type": "Gene",
            "id": "gene_a",
            "category": "innovate",
            "target_hook": "improver_tool",
            "mechanism_family": "improver_tools",
            "signals_match": ["inspection_difficulty"],
            "strategy": ["Add a bounded inspection tool"],
            "constraints": {"max_files": 1, "forbidden_paths": []},
            "validation": ["python --version"],
        }
    )
    save_evidence("run_1", "evt_1_abc", scene())
    stored = episode_record.record_round(event_id="evt_1_abc")
    assert stored["ok"] is True
    body = episode_record.load_episode(stored["id"])
    assert body is not None
    assert body["gene"]["target_hook"] == "improver_tool"
    assert body["gene"]["mechanism_family"] == "improver_tools"


def test_the_bundled_seed_carries_improver_tool_genes() -> None:
    """经验即证据 §5.4: the improver's tool surface is first-class — the seed
    library carries improver-tool genes the selector can choose."""
    from evolver.gep.asset_store import genes_seed_path

    seed = json.loads(genes_seed_path().read_text(encoding="utf-8"))
    improver = [g for g in seed["genes"] if g.get("target_hook") == "improver_tool"]
    assert len(improver) == 3
    for gene in improver:
        assert gene["mechanism_family"] == "improver_tools"
        assert gene.get("asset_id", "").startswith("sha256:")
