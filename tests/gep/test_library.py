"""Tests for evolver.gep.library (charter 配对会话 §5.4).

A content-dimension candidate is consulted as a library snapshot, and during
the comparison ``active`` still points at the Parent. Three rules make that
trustworthy: publish never overwrites, only publishing moves ``active``, and
reading a version by id is a read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import library


@pytest.fixture
def library_env(temp_workspace: Path) -> Path:
    return temp_workspace


PARENT = {"genes": [{"id": "gene_a", "strategy": ["do the thing"]}], "capsules": []}
CHILD = {"genes": [{"id": "gene_a", "strategy": ["do the thing", "then check"]}], "capsules": []}


def test_an_empty_library_has_no_active_snapshot(library_env: Path) -> None:
    assert library.active_snapshot_id() is None
    assert library.load_active() is None


def test_identical_content_gets_an_identical_id(library_env: Path) -> None:
    assert library.snapshot_id(PARENT) == library.snapshot_id(dict(PARENT))
    assert library.snapshot_id(PARENT) != library.snapshot_id(CHILD)


def test_saving_the_same_snapshot_twice_is_idempotent(library_env: Path) -> None:
    first = library.save_version(PARENT)
    second = library.save_version(PARENT)
    assert first["snapshot"] == second["snapshot"]
    assert second["reason"] == "already_stored"


def test_publish_never_overwrites_a_version(library_env: Path) -> None:
    """Two different libraries must never share an id: the id is what
    ``active`` and every run record cite, so overwriting would silently
    change the meaning of every older citation."""
    snap = library.snapshot_id(PARENT)
    library.save_version(PARENT)
    target = library.version_path(snap)
    target.write_text(json.dumps(CHILD), encoding="utf-8")  # corrupt/divergent bytes
    with pytest.raises(library.SnapshotConflictError):
        library.save_version(PARENT)


def test_publish_moves_active_and_reports_where_it_came_from(library_env: Path) -> None:
    library.publish(PARENT, session_id="s1", run_id="r1")
    parent_snap = library.snapshot_id(PARENT)
    assert library.active_snapshot_id() == parent_snap

    result = library.publish(CHILD, session_id="s1", run_id="r1")
    assert result["previous"] == parent_snap
    assert library.active_snapshot_id() == library.snapshot_id(CHILD)


def test_reading_a_version_does_not_make_it_active(library_env: Path) -> None:
    """During a comparison this is the whole point: the candidate may be
    read without becoming the thing the Parent is measured against."""
    library.publish(PARENT)
    child_snap = library.save_version(CHILD)["snapshot"]

    assert library.load_version(child_snap) == CHILD
    assert library.active_snapshot_id() == library.snapshot_id(PARENT)


def test_load_active_returns_the_published_payload(library_env: Path) -> None:
    library.publish(CHILD)
    assert library.load_active() == CHILD


def test_a_non_object_snapshot_is_refused(library_env: Path) -> None:
    with pytest.raises(library.SnapshotConflictError):
        library.save_version(["not", "an", "object"])  # type: ignore[arg-type]


def test_a_missing_version_reads_as_none(library_env: Path) -> None:
    assert library.load_version("sha256:does-not-exist") is None


def test_snapshot_of_a_payload(library_env: Path) -> None:
    assert library.snapshot_of(PARENT) == library.snapshot_id(PARENT)
    assert library.snapshot_of(None) is None


# ---------------------------------------------------------------------------
# In-cycle consultation (charter §5.4): the loop reads the published library
# as design context while active still points at Parent.
# ---------------------------------------------------------------------------


async def test_enrich_consults_the_published_library(library_env: Path) -> None:
    """The enrich phase hands the candidate the Parent line's snapshot as
    read-only design context — and the read leaves active untouched."""
    from evolver.evolve.pipeline.enrich import enrich_phase

    library.publish(PARENT)
    ctx = await enrich_phase({"signals": [], "genes": [], "capsules": []})

    assert ctx["library_active_id"] == library.snapshot_id(PARENT)
    block = ctx["library_block"]
    assert library.snapshot_id(PARENT) in block
    assert "do the thing" in block  # the payload itself is the context
    assert "read-only design context" in block
    # Consultation is a read: active still points at the Parent.
    assert library.active_snapshot_id() == library.snapshot_id(PARENT)


async def test_an_empty_library_contributes_no_block(library_env: Path) -> None:
    from evolver.evolve.pipeline.enrich import enrich_phase

    ctx = await enrich_phase({"signals": [], "genes": [], "capsules": []})
    assert "library_block" not in ctx
    assert "library_active_id" not in ctx


async def test_a_large_snapshot_is_truncated_with_a_marker(library_env: Path) -> None:
    from evolver.evolve.pipeline.enrich import LIBRARY_BLOCK_MAX_CHARS, enrich_phase

    big = {"notes": "x" * (LIBRARY_BLOCK_MAX_CHARS * 3)}
    library.publish(big)
    ctx = await enrich_phase({"signals": [], "genes": [], "capsules": []})
    assert "truncated" in ctx["library_block"]
    assert ctx["library_active_id"] == library.snapshot_id(big)


async def test_the_dispatch_run_record_names_the_consulted_snapshot(
    library_env: Path,
) -> None:
    """The solidify state carries the consulted id — the comparison can then
    show WHICH library a candidate was built against while active still
    pointed at Parent."""
    from evolver.evolve.pipeline.dispatch import _write_solidify_state
    from evolver.evolve.pipeline.enrich import enrich_phase
    from evolver.gep.solidify import _read_solidify_state

    library.publish(PARENT)
    ctx = await enrich_phase({"signals": [], "genes": [], "capsules": []})
    _write_solidify_state(ctx)

    state = _read_solidify_state()
    assert state["last_run"]["library_snapshot"] == library.snapshot_id(PARENT)


# ---------------------------------------------------------------------------
# round-93: the establish_* first-write and its call-graph discipline
# ---------------------------------------------------------------------------


def test_before_the_first_write_there_is_no_parent(library_env: Path) -> None:
    assert library.parent_snapshot_id() is None


def test_establish_writes_the_parent_pointer_and_never_touches_active(
    library_env: Path,
) -> None:
    result = library.establish_parent_library(PARENT)
    assert result["ok"] is True and result["reason"] == "parent_established"
    assert result["snapshot"] == library.snapshot_id(PARENT)
    assert library.parent_snapshot_id() == library.snapshot_id(PARENT)
    assert library.load_version(library.snapshot_id(PARENT)) == PARENT
    # active moves only on Accept: establish is the human's first-write
    assert result["active_untouched"] is None
    assert library.active_snapshot_id() is None


def test_establish_same_content_twice_is_idempotent(library_env: Path) -> None:
    first = library.establish_parent_library(PARENT)
    second = library.establish_parent_library(dict(PARENT))
    assert second["reason"] == "already_stored"
    assert second["snapshot"] == first["snapshot"]
    assert library.parent_snapshot_id() == first["snapshot"]


def test_reestablishing_different_content_moves_the_pointer_and_reports_previous(
    library_env: Path,
) -> None:
    first = library.establish_parent_library(PARENT)
    second = library.establish_parent_library(CHILD)
    assert second["previous"] == first["snapshot"]
    assert library.parent_snapshot_id() == library.snapshot_id(CHILD)
    # versions are never deleted: the old snapshot stays loadable by id
    assert library.load_version(first["snapshot"]) == PARENT


def test_save_version_alone_never_moves_active_or_parent(library_env: Path) -> None:
    library.save_version(CHILD)
    assert library.active_snapshot_id() is None
    assert library.parent_snapshot_id() is None


def test_establish_is_absent_from_the_solidify_call_graph() -> None:
    """round-93 discipline pin: the first-write must be unreachable from the
    engine's cycle. solidify's call graph (the module and the evolve
    pipeline) must not reference it — the only entry is the human CLI."""
    repo = Path(__file__).resolve().parents[2]
    guarded = [
        repo / "src/evolver/gep/solidify.py",
        *sorted((repo / "src/evolver/evolve").rglob("*.py")),
    ]
    assert guarded, "call-graph scan found no files"
    for path in guarded:
        assert "establish_parent_library" not in path.read_text(encoding="utf-8"), (
            f"{path.name} references establish_parent_library — the first-write "
            "must stay outside the engine cycle"
        )


def test_render_prompt_block_pastes_content_and_keeps_the_confine(library_env: Path) -> None:
    block = library.render_prompt_block(library.snapshot_id(PARENT), PARENT)
    assert library.snapshot_id(PARENT) in block
    assert "do the thing" in block  # the payload itself, pasted
    assert "Do NOT open or edit any library store" in block


def test_render_prompt_block_truncates_past_the_budget(library_env: Path) -> None:
    big = {"genes": [{"id": f"g{i}", "strategy": ["x" * 200]} for i in range(100)]}
    block = library.render_prompt_block("sha256:big", big)
    assert "truncated" in block
