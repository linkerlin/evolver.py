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


def test_solidify_with_proposal(ws: Path) -> None:
    import subprocess

    from evolver.gep.solidify import solidify, write_state_for_solidify

    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=ws, check=True
    )

    write_state_for_solidify({"run_id": "run_prop_1", "selected_gene_id": "gene_x"})
    proposal = _patch()

    res = solidify(skip_validation=True, proposal=proposal)
    assert res["ok"] is True
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8").startswith("TIMEOUT = 60")
    assert res["proposal"]["applied"] is True
    assert res["proposal"]["files_changed"] == ["src/mod.py"]


def test_solidify_with_proposal_anchor_miss_aborts(ws: Path) -> None:
    import subprocess

    from evolver.gep.solidify import solidify, write_state_for_solidify

    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=ws, check=True
    )

    write_state_for_solidify({"run_id": "run_prop_2", "selected_gene_id": "gene_x"})
    bad_proposal = _patch(
        edits=[
            {
                "op": "replace",
                "file": "src/mod.py",
                "target": "NON_EXISTENT_ANCHOR",
                "content": "BAD",
            }
        ]
    )

    res = solidify(skip_validation=True, proposal=bad_proposal)
    assert res["ok"] is False
    assert res.get("error") == "proposal_rejected"
    assert "anchor not found" in res.get("message", "")
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8").startswith("TIMEOUT = 30")


def test_solidify_proposal_no_action(ws: Path) -> None:
    from evolver.gep.solidify import solidify, write_state_for_solidify

    write_state_for_solidify({"run_id": "run_prop_3", "selected_gene_id": "gene_x"})
    proposal = {"action": "no_action"}

    res = solidify(skip_validation=True, proposal=proposal)
    assert res["ok"] is True
    assert res["proposal"]["applied"] is False
    assert res["proposal"]["action"] == "no_action"


def test_swarm_propose_tool(ws: Path) -> None:
    from evolver.swarm import swarm_propose

    valid_proposal = _patch()
    res = swarm_propose(valid_proposal)
    assert res["ok"] is True
    assert res["action"] == "patch"
    assert res["files_changed"] == ["src/mod.py"]
    assert res["next_action"] == "swarm_solidify"
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8").startswith("TIMEOUT = 60")

    # Subsequent propose with now-outdated anchor gets rejected
    res2 = swarm_propose(valid_proposal)
    assert res2["ok"] is False
    assert res2["error"] == "proposal_rejected"
    assert "anchor not found" in res2["message"]


def test_cli_solidify_proposal(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    from evolver.cli import main
    from evolver.gep.solidify import write_state_for_solidify

    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=ws, check=True
    )

    write_state_for_solidify({"run_id": "run_prop_cli", "selected_gene_id": "gene_x"})
    prop_file = tmp_path / "prop_cli.json"
    prop_file.write_text(json.dumps(_patch()), encoding="utf-8")

    code = main(["solidify", "--proposal", str(prop_file)])
    assert code == 0
    assert (ws / "src" / "mod.py").read_text(encoding="utf-8").startswith("TIMEOUT = 60")
    assert "Solidify succeeded" in capsys.readouterr().out
