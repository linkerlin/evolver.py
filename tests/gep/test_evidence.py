"""S28.1 immutable evidence layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.evidence import (
    evidence_dir,
    load_evidence,
    save_evidence,
)


@pytest.fixture
def gep_dir(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = temp_workspace / ".evolver" / "gep"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(d))
    return d


def test_save_and_load_roundtrip(gep_dir: Path) -> None:
    path = save_evidence("run-1", "evt_abc", {"score": 1.0, "ok": True})
    assert path.exists()
    assert load_evidence("run-1", "evt_abc") == {"score": 1.0, "ok": True}
    assert path.parent == evidence_dir("run-1")


def test_immutability_second_write_raises(gep_dir: Path) -> None:
    save_evidence("run-1", "evt_abc", {"score": 1.0})
    with pytest.raises(FileExistsError, match="immutable"):
        save_evidence("run-1", "evt_abc", {"score": 0.0})
    # the original evidence is untouched — no silent history rewrite
    assert load_evidence("run-1", "evt_abc") == {"score": 1.0}


def test_replay_is_byte_identical(gep_dir: Path) -> None:
    """Replaying a cycle must reproduce identical evidence bytes."""
    payload = {"event": {"id": "e1", "score": 0.98}, "verdict": "improved"}
    first = save_evidence("run-2", "e1", payload)
    raw = first.read_text(encoding="utf-8")
    # same payload into a fresh dir renders the same bytes
    second = save_evidence("run-3", "e1", payload)
    assert second.read_text(encoding="utf-8") == raw
    assert json.loads(raw) == payload


def test_rejects_unsafe_ids(gep_dir: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        evidence_dir("../escape")
    with pytest.raises(ValueError, match="kind"):
        save_evidence("run-1", "a/b", {"x": 1})
