"""S27.2 wiki patterns projection — machine state → human-readable pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.wiki_projection import project_patterns

LESSONS = """---
last_updated: "2026-09-02T00:00:00Z"
evolution_count: 3
friction_points:
  - id: fp1
    category: tooling
    description: ruff timeout too tight
    status: open
  - id: fp2
    category: harness
    description: dead session counted as work
    status: resolved
---

# Lessons Learned
"""


@pytest.fixture
def proj_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    evo = tmp_path / "evo"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("MEMORY_GRAPH_STATE_PATH", str(evo / "memory_graph_state.json"))
    (evo / "LESSONS_LEARNED.md").write_text(LESSONS, encoding="utf-8")
    (evo / "memory_graph_state.json").write_text(
        '{"preferred_by_signal": {"errsig:timeout": {"gene_a": 3, "gene_b": 1}}}',
        encoding="utf-8",
    )
    return evo


def test_projection_writes_pages_and_index(proj_ws: Path) -> None:
    pages = project_patterns()
    assert [p.name for p in pages] == ["friction.md", "preferred-genes.md"]
    friction = (proj_ws / "wiki" / "patterns" / "friction.md").read_text(encoding="utf-8")
    assert "ruff timeout too tight" in friction
    assert "| tooling |" in friction
    preferred = (proj_ws / "wiki" / "patterns" / "preferred-genes.md").read_text(encoding="utf-8")
    assert "errsig:timeout" in preferred
    assert "gene_a×3" in preferred
    index = (proj_ws / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "[friction.md](patterns/friction.md)" in index
    assert "[preferred-genes.md](patterns/preferred-genes.md)" in index


def test_projection_is_idempotent(proj_ws: Path) -> None:
    project_patterns()
    first = (proj_ws / "wiki" / "patterns" / "friction.md").read_bytes()
    project_patterns()
    second = (proj_ws / "wiki" / "patterns" / "friction.md").read_bytes()
    assert first == second


def test_projection_survives_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evo = tmp_path / "evo"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("MEMORY_GRAPH_STATE_PATH", str(evo / "memory_graph_state.json"))
    pages = project_patterns()
    assert len(pages) == 2
    body = (evo / "wiki" / "patterns" / "friction.md").read_text(encoding="utf-8")
    assert "No friction points recorded" in body
