"""Tests for evolver.ops.cleanup."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from evolver.ops import cleanup


def test_cleanup_jsonl_removes_old(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    old_ts = int((time.time() - 86400) * 1000)  # 1 day old
    new_ts = int(time.time() * 1000)
    path.write_text(
        json.dumps({"id": "e1", "timestamp": old_ts})
        + "\n"
        + json.dumps({"id": "e2", "timestamp": new_ts})
        + "\n",
        encoding="utf-8",
    )
    result = cleanup.cleanup_jsonl(path, max_age_ms=3600_000, min_keep=1)
    assert result["removed"] == 1
    assert result["kept"] == 1
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "e2"


def test_cleanup_jsonl_keeps_min_keep(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    old_ts = int((time.time() - 86400) * 1000)
    path.write_text(
        "\n".join(json.dumps({"id": f"e{i}", "timestamp": old_ts}) for i in range(3)) + "\n",
        encoding="utf-8",
    )
    result = cleanup.cleanup_jsonl(path, max_age_ms=0, min_keep=2)
    assert result["removed"] == 1
    assert result["kept"] == 2


def test_cleanup_directory_removes_old_files(tmp_path: Path) -> None:
    f1 = tmp_path / "a.log"
    f2 = tmp_path / "b.log"
    f1.write_text("old")
    f2.write_text("new")
    import os

    old = time.time() - 86400 * 2
    os.utime(f1, (old, old))
    result = cleanup.cleanup_directory(
        tmp_path, pattern="*.log", max_age_ms=3600_000, max_files=10, min_keep=1
    )
    assert result["removed"] == 1
    assert not f1.exists()
    assert f2.exists()


def test_cleanup_directory_respects_max_files(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"{i}.log").write_text("x")
    result = cleanup.cleanup_directory(
        tmp_path, pattern="*.log", max_age_ms=999999999, max_files=2, min_keep=0
    )
    assert result["removed"] == 3
    assert len(list(tmp_path.glob("*.log"))) == 2


def test_run_cleanup_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evo"))
    monkeypatch.setenv("EVOLVER_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    result = cleanup.run_cleanup()
    assert result["ok"] is True
    assert result["total_removed"] == 0
