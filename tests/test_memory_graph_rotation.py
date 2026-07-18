"""Regression guard for #519: memory_graph.jsonl rotation.

Ports Node's ``test/memoryGraphRotation.test.js`` (8 contracts).
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest

from evolver.gep import memory_graph as mg

_ARCHIVE_RE = re.compile(r"memory_graph\.jsonl\.\d+")


def _archives(tmp_dir: Path) -> list[str]:
    return sorted(p.name for p in tmp_dir.iterdir() if _ARCHIVE_RE.search(p.name))


@pytest.fixture
def rotate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate rotation env vars into a temp dir (Node beforeEach equivalent)."""
    for key in (
        "EVOLVER_MEMORY_GRAPH_AUTO_ROTATE",
        "EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB",
        "EVOLVER_MEMORY_GRAPH_RETENTION_COUNT",
        "EVOLVER_ROTATE_GZIP_MAX_MB",
        "MEMORY_GRAPH_PATH",
        "MEMORY_DIR",
        "EVOLUTION_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    # Reset throttle counters between tests.
    mg._rotate_throttle["writes_since_check"] = 0
    mg._rotate_throttle["last_check_at"] = 0.0
    return tmp_path


def test_rotates_when_active_file_exceeds_max_size(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "0.01")  # 10 KB
    active_path = Path(rotate_env / "memory_graph.jsonl")
    active_path.write_bytes(b"x" * (20 * 1024))

    renamed = mg.maybe_rotate_memory_graph(active_path, force=True)

    assert renamed, "expected rotation to return the archive path"
    assert (not active_path.exists()) or active_path.stat().st_size == 0
    archives = _archives(rotate_env)
    assert len(archives) >= 1
    gz = next((n for n in archives if n.endswith(".gz")), None)
    assert gz, "expected archive to be gzip-compressed"
    decoded = gzip.decompress((rotate_env / gz).read_bytes())
    assert len(decoded) == 20 * 1024


def test_rotates_oversized_file_at_startup(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "0.01")
    active_path = Path(rotate_env / "memory_graph.jsonl")
    active_path.write_bytes(b"x" * (20 * 1024))

    # Equivalent to Node freshRequire: call the boot-time rotation hook.
    mg.rotate_on_startup_if_oversized()

    assert (not active_path.exists()) or active_path.stat().st_size == 0
    archives = _archives(rotate_env)
    assert len(archives) >= 1


def test_does_not_rotate_when_file_below_threshold(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "100")
    active_path = Path(rotate_env / "memory_graph.jsonl")
    active_path.write_bytes(b"x" * 1024)

    renamed = mg.maybe_rotate_memory_graph(active_path, force=True)

    assert renamed is None
    assert active_path.exists()
    assert _archives(rotate_env) == []


def test_respects_auto_rotate_opt_out(rotate_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_AUTO_ROTATE", "false")
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "0.001")
    active_path = Path(rotate_env / "memory_graph.jsonl")
    active_path.write_bytes(b"x" * (10 * 1024))

    renamed = mg.maybe_rotate_memory_graph(active_path, force=True)

    assert renamed is None
    assert active_path.exists()


def test_prunes_rotated_archives_beyond_retention(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_RETENTION_COUNT", "2")
    active_path = Path(rotate_env / "memory_graph.jsonl")
    for ts in (
        "20260401000000",
        "20260402000000",
        "20260403000000",
        "20260404000000",
        "20260405000000",
    ):
        (rotate_env / f"memory_graph.jsonl.{ts}.gz").write_text("archive", encoding="utf-8")

    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "0.001")
    active_path.write_bytes(b"x" * (10 * 1024))
    mg.maybe_rotate_memory_graph(active_path, force=True)

    archives = _archives(rotate_env)
    assert len(archives) == 2, "only retention_count newest archives should remain"


def test_exposes_config_helpers_that_read_current_env(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = rotate_env
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "42")
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_RETENTION_COUNT", "3")
    assert mg.rotation_max_size_bytes() == 42 * 1024 * 1024
    assert mg.rotation_retention_count() == 3
    assert mg.rotation_enabled() is True


def test_uses_sane_defaults_when_env_absent_or_invalid(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = rotate_env
    assert mg.rotation_max_size_bytes() == 100 * 1024 * 1024
    assert mg.rotation_retention_count() == 7

    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "not-a-number")
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_RETENTION_COUNT", "-1")
    assert mg.rotation_max_size_bytes() == 100 * 1024 * 1024
    assert mg.rotation_retention_count() == 7


def test_accepts_zero_as_retention_delete_all(
    rotate_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_RETENTION_COUNT", "0")
    assert mg.rotation_retention_count() == 0

    active_path = Path(rotate_env / "memory_graph.jsonl")
    (rotate_env / "memory_graph.jsonl.20260401000000.gz").write_text("a", encoding="utf-8")
    (rotate_env / "memory_graph.jsonl.20260402000000.gz").write_text("b", encoding="utf-8")

    monkeypatch.setenv("EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB", "0.001")
    active_path.write_bytes(b"x" * (10 * 1024))
    mg.maybe_rotate_memory_graph(active_path, force=True)

    archives = _archives(rotate_env)
    assert archives == [], "retention=0 should delete every archive including the just-rotated one"
