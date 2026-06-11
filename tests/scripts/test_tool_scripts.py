"""Smoke tests for scripts/*.py CLI tools."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _run(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=REPO,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gep_append_event(temp_workspace: Path) -> None:
    proc = _run(
        "gep_append_event.py",
        "--type",
        "test_note",
        "--message",
        "hello",
        env={"GEP_ASSETS_DIR": str(temp_workspace / "gep")},
    )
    assert proc.returncode == 0
    events_file = temp_workspace / "gep" / "events.jsonl"
    assert events_file.exists()
    line = events_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    evt = json.loads(line)
    assert evt["type"] == "test_note"


def test_recover_loop_runs(temp_workspace: Path) -> None:
    proc = _run(
        "recover_loop.py",
        env={
            "EVOLUTION_DIR": str(temp_workspace / "evolution"),
            "EVOLVER_NO_PARENT_GIT": "1",
        },
    )
    assert proc.returncode == 0
    assert "Evolver loop recovery" in proc.stdout


def test_generate_history_empty(temp_workspace: Path) -> None:
    out = temp_workspace / "history.md"
    proc = _run(
        "generate_history.py",
        "-o",
        str(out),
        env={"GEP_ASSETS_DIR": str(temp_workspace / "gep")},
    )
    assert proc.returncode == 0
    assert out.exists()


def test_a2a_promote_latest(temp_workspace: Path) -> None:
    gep = temp_workspace / "gep"
    gep.mkdir(parents=True)
    candidate = {
        "id": "cand-1",
        "gene": {
            "type": "Gene",
            "id": "gene-promote-1",
            "category": "repair",
            "signals_match": ["error"],
            "strategy": ["fix"],
            "validation": ["noop"],
        },
    }
    (gep / "candidates.jsonl").write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    proc = _run("a2a_promote.py", "--latest", env={"GEP_ASSETS_DIR": str(gep)})
    assert proc.returncode == 0
    assert "Promoted gene" in proc.stdout
    assert (gep / "genes.jsonl").exists()


def test_seed_merchants(temp_workspace: Path) -> None:
    proc = _run(
        "seed_merchants.py",
        "--output",
        str(temp_workspace / "atp_seed.json"),
        env={"MEMORY_DIR": str(temp_workspace / "memory"), "EVOLVER_HOME": str(temp_workspace)},
    )
    assert proc.returncode == 0
    assert (temp_workspace / "atp_seed.json").exists()


def test_check_changelog_create_stub() -> None:
    proc = _run("check_changelog.py", "--create-stub")
    assert proc.returncode in (0, 1)


def test_suggest_version() -> None:
    proc = _run("suggest_version.py")
    assert proc.returncode == 0
    assert "current:" in proc.stdout


def test_build_binaries_check_only() -> None:
    proc = _run("build_binaries.py", "--check-only")
    assert proc.returncode in (0, 1)


def test_a2a_export_ingest_roundtrip(temp_workspace: Path) -> None:
    gep = temp_workspace / "gep"
    env = {"GEP_ASSETS_DIR": str(gep)}
    export_path = temp_workspace / "bundle.json"
    proc = _run("a2a_export.py", "-o", str(export_path), env=env)
    assert proc.returncode == 0
    assert export_path.exists()

    gep2 = temp_workspace / "gep2"
    proc = _run(
        "a2a_ingest.py",
        str(export_path),
        "--mode",
        "merge",
        env={"GEP_ASSETS_DIR": str(gep2)},
    )
    assert proc.returncode == 0
    assert (gep2 / "genes.json").exists() or (gep2 / "genes.jsonl").exists()


def test_analyze_by_skill_empty(temp_workspace: Path) -> None:
    proc = _run(
        "analyze_by_skill.py",
        env={
            "GEP_ASSETS_DIR": str(temp_workspace / "gep"),
            "OPENCLAW_WORKSPACE": str(temp_workspace),
            "EVOLVER_NO_PARENT_GIT": "1",
        },
    )
    assert proc.returncode == 0
