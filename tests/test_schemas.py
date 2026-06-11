"""Tests for GEP schemas — equivalent to evolver/test/schema*.test.js."""

from __future__ import annotations

import pytest

from evolver.gep.schemas import (
    create_capsule,
    create_gene,
    create_task,
    validate_capsule,
    validate_gene,
    validate_task,
)


def test_gene_defaults() -> None:
    g = create_gene()
    assert g.type == "Gene"
    assert g.category == "innovate"
    assert g.constraints.max_files == 20
    assert ".git" in g.constraints.forbidden_paths


def test_gene_validates_required_fields() -> None:
    g = create_gene({"id": "gene_test", "category": "repair"})
    assert validate_gene(g) is True


def test_gene_rejects_missing_id() -> None:
    g = create_gene()
    with pytest.raises(ValueError, match="Gene.id is required"):
        validate_gene(g)


def test_gene_normalizes_invalid_category() -> None:
    g = create_gene({"category": "not_a_category"})
    assert g.category == "innovate"


def test_capsule_defaults() -> None:
    c = create_capsule()
    assert c.type == "Capsule"
    assert c.outcome.status == "failed"
    assert c.blast_radius.files == 0


def test_capsule_rejects_missing_id() -> None:
    c = create_capsule()
    with pytest.raises(ValueError, match="Capsule.id is required"):
        validate_capsule(c)


def test_task_defaults() -> None:
    t = create_task()
    assert t.type == "Task"
    assert t.status == "open"


def test_task_rejects_missing_id() -> None:
    t = create_task()
    with pytest.raises(ValueError, match="Task.task_id is required"):
        validate_task(t)
