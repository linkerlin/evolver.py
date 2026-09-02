"""S29 gene proposals: mechanical application with hard validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evolver.gep.proposal import (
    GeneProposal,
    apply_proposal,
    parse_proposal,
)


def _patch(**overrides: dict) -> dict:
    data: dict = {
        "action": "patch",
        "gene_id": "gene_x",
        "edits": [
            {
                "op": "replace",
                "file": "src/mod.py",
                "target": "TIMEOUT = 30",
                "content": "TIMEOUT = 60",
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def ws(temp_workspace: Path) -> Path:
    mod = temp_workspace / "src" / "mod.py"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_text("TIMEOUT = 30\nRETRIES = 2\n", encoding="utf-8")
    return temp_workspace


def test_parse_rejects_inconsistent_proposals() -> None:
    with pytest.raises(ValidationError):
        parse_proposal({"action": "no_action", "edits": _patch()["edits"]})
    with pytest.raises(ValidationError):
        parse_proposal({"action": "patch", "edits": []})
    with pytest.raises(ValidationError):
        parse_proposal(
            {
                "action": "patch",
                "edits": [{"op": "replace", "file": "a.py", "content": "x"}],  # no target
            }
        )
    with pytest.raises(ValidationError):
        parse_proposal(
            {
                "action": "patch",
                "edits": [{"op": "append", "file": "a.py", "content": "x", "target": "y"}],
            }
        )


def test_no_action_is_first_class(ws: Path) -> None:
    report = apply_proposal(GeneProposal(action="no_action", note="nothing worth changing"), ws)
    assert report["applied"] is False
    assert report["files_changed"] == []


def test_patch_replace_mechanical(ws: Path) -> None:
    proposal = parse_proposal(_patch())
    report = apply_proposal(proposal, ws)
    assert report["applied"] is True
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8") == "TIMEOUT = 60\nRETRIES = 2\n"


def test_anchor_miss_rejects_entire_proposal(ws: Path) -> None:
    """A hallucinated anchor raises and NOTHING is written (validate-all-first)."""
    proposal = parse_proposal(
        _patch(
            edits=[
                {"op": "append", "file": "src/new.py", "content": "good\n"},
                {
                    "op": "replace",
                    "file": "src/mod.py",
                    "target": "THIS LINE DOES NOT EXIST",
                    "content": "x",
                },
            ]
        )
    )
    with pytest.raises(ValueError, match="anchor not found"):
        apply_proposal(proposal, ws)
    assert not (ws / "src" / "new.py").exists()  # clean rejection
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8").startswith("TIMEOUT = 30")


def test_ambiguous_anchor_rejected(ws: Path) -> None:
    (ws / "src" / "mod.py").write_text("X = 1\nX = 1\n", encoding="utf-8")
    proposal = parse_proposal(
        _patch(
            edits=[{"op": "replace", "file": "src/mod.py", "target": "X = 1", "content": "X = 2"}]
        )
    )
    with pytest.raises(ValueError, match="ambiguous"):
        apply_proposal(proposal, ws)


def test_insert_after_and_append_ops(ws: Path) -> None:
    proposal = parse_proposal(
        _patch(
            edits=[
                {
                    "op": "insert_after",
                    "file": "src/mod.py",
                    "target": "RETRIES = 2",
                    "content": "\nBACKOFF = 5",
                },
                {"op": "append", "file": "src/mod.py", "content": "\n# tail\n"},
            ]
        )
    )
    apply_proposal(proposal, ws)
    text = (ws / "src" / "mod.py").read_text(encoding="utf-8")
    assert "RETRIES = 2\nBACKOFF = 5" in text
    assert text.endswith("# tail\n")


def test_create_requires_absent_file(ws: Path) -> None:
    proposal = parse_proposal(
        {
            "action": "create",
            "edits": [{"op": "append", "file": "src/new.py", "content": "x = 1\n"}],
        }
    )
    apply_proposal(proposal, ws)
    assert (ws / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    with pytest.raises(ValueError, match="already exists"):
        apply_proposal(proposal, ws)


def test_path_escape_rejected(ws: Path) -> None:
    for bad in ("../evil.py", "/abs/path.py", ".git/config", ".venv/lib/x.py"):
        proposal = parse_proposal(_patch(edits=[{"op": "append", "file": bad, "content": "x"}]))
        with pytest.raises(ValueError):
            apply_proposal(proposal, ws)


def test_roundtrip_from_json_file(ws: Path, tmp_path: Path) -> None:
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(_patch()), encoding="utf-8")
    proposal = parse_proposal(json.loads(path.read_text(encoding="utf-8")))
    report = apply_proposal(proposal, ws)
    assert report["files_changed"] == ["src/mod.py"]
