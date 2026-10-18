"""episode_inspect reads the lossless scene without writing it."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import episode_record
from evolver.gep.evidence import save_evidence


def _scene(stdout: str, diff: str) -> dict[str, object]:
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": "evt_zoom",
            "run_id": "run_zoom",
            "timestamp": "2026-10-18T00:00:00.000Z",
            "gene_id": "gene_zoom",
            "mutation": {"id": "mut_zoom", "category": "repair"},
            "diff_snapshot": diff,
            "outcome": {"status": "failed", "score": 0.0},
        },
        "validation_result": {
            "ok": False,
            "results": [
                {
                    "command": "uv run pytest",
                    "ok": False,
                    "stdout": stdout,
                    "stderr": "",
                }
            ],
        },
        "gate": {"accepted": False},
    }


def test_empty_question_is_refused(temp_workspace: Path) -> None:
    result = episode_record.inspect_episode_scene("sha256:none", question="  ", views=[])
    assert result["ok"] is False
    assert result["error"] == "empty_question"
    assert result["current_state_unchanged"] is True


def test_inspect_reads_past_the_clipped_check(temp_workspace: Path) -> None:
    stdout = "HEAD\n" + ("line\n" * 200) + "TAIL-NEEDLE"
    diff = "diff --git a/src/a.py b/src/a.py\n" + "+kept\n" * 50
    save_evidence("run_zoom", "evt_zoom", _scene(stdout, diff))
    body = episode_record.build_episode(_scene(stdout, diff))  # type: ignore[arg-type]
    stored = episode_record.record_episode(body)
    assert "TAIL-NEEDLE" not in body["checks"][0]["stdout"]
    block = episode_record.render_episode_block(body, ep_id=stored["id"])
    assert "episode_inspect" in block

    before = episode_record.episode_path(stored["id"]).read_bytes()
    zoomed = episode_record.inspect_episode_scene(
        stored["id"],
        question="the failure is past the clip",
        views=[
            {"kind": "check", "name": "pytest", "offset_lines": 180, "limit_lines": 40},
            {"kind": "diff", "path_glob": "src/*.py", "offset_lines": 0, "limit_lines": 5},
        ],
    )
    assert zoomed["ok"] is True
    assert zoomed["current_state_unchanged"] is True
    assert zoomed["question"]["source"] == "host_query"
    assert "TAIL-NEEDLE" in zoomed["views"][0]["text"]
    assert zoomed["views"][0]["source"] == "engine"
    assert "+kept" in zoomed["views"][1]["text"]
    assert episode_record.episode_path(stored["id"]).read_bytes() == before


def test_host_inspect_is_logged_beside_the_record(temp_workspace: Path) -> None:
    from evolver.gep.evolution_session import EvolutionSession
    from evolver.mcp_server import episode_inspect

    save_evidence("run_zoom", "evt_zoom", _scene("out", "diff --git a/a.py b/a.py\n+x\n"))
    stored = episode_record.record_episode(
        episode_record.build_episode(_scene("out", "+x\n"))  # type: ignore[arg-type]
    )
    before = episode_record.episode_path(stored["id"]).read_bytes()
    view = {"kind": "check", "name": "pytest", "offset_lines": 0, "limit_lines": 5}

    episode_record.inspect_episode_scene(stored["id"], question="pure read", views=[view])
    assert episode_record.load_inspect_calls() == []

    session = EvolutionSession()
    session.start_run("parent-snapshot-aaa")
    assert episode_inspect(stored["id"], "where did it fail", [view])["ok"] is True
    assert episode_inspect(stored["id"], "", [view])["ok"] is False

    calls = episode_record.load_inspect_calls()
    assert len(calls) == 1
    assert calls[0]["episode_id"] == stored["id"]
    assert calls[0]["run_id"] == "run_zoom"
    assert calls[0]["session_run_id"] == session.run_id
    assert calls[0]["view_kinds"] == ["check"]
    assert "where did it fail" not in str(calls)
    assert episode_record.episode_path(stored["id"]).read_bytes() == before


def test_inspect_redacts_through_val_seal(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_evidence("run_zoom", "evt_zoom", _scene("SECRET-LINE", "diff --git a/a.py b/a.py\n+x\n"))
    stored = episode_record.record_episode(
        episode_record.build_episode(_scene("SECRET-LINE", "+x\n"))  # type: ignore[arg-type]
    )

    def _redact(text: str, *, where: str) -> tuple[str, dict[str, int]]:
        assert where == "episode_inspect"
        return text.replace("SECRET-LINE", "[sealed:val]"), {"redacted": 1}

    monkeypatch.setattr("evolver.gep.val_seal.redact", _redact)
    zoomed = episode_record.inspect_episode_scene(
        stored["id"],
        question="where is SECRET-LINE",
        views=[{"kind": "check", "name": "pytest", "offset_lines": 0, "limit_lines": 20}],
    )
    assert "[sealed:val]" in zoomed["views"][0]["text"]
    assert "SECRET-LINE" not in zoomed["views"][0]["text"]
