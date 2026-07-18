"""Tests for cycle hard-timeout, progress file, and spawn replacement (Sprint 14.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evolver.cycle_control import (
    CycleTimeoutError,
    handle_cycle_timeout,
    parse_bool_env,
    parse_ms_env,
    spawn_replacement_process,
    write_cycle_progress_atomic,
)

# ---------------------------------------------------------------------------
# CycleTimeoutError
# ---------------------------------------------------------------------------


def test_cycle_timeout_error_fields() -> None:
    err = CycleTimeoutError(2_700_000, "evolve.run", 5372)
    assert isinstance(err, TimeoutError)
    assert err.name == "CycleTimeoutError"
    assert err.code == "CYCLE_TIMEOUT"
    assert err.timeout_ms == 2_700_000
    assert err.phase == "evolve.run"
    assert err.cycle_num == 5372
    assert "2700000ms" in str(err)
    assert "cycle=5372" in str(err)
    assert "phase=evolve.run" in str(err)


# ---------------------------------------------------------------------------
# parse_bool_env
# ---------------------------------------------------------------------------


def test_parse_bool_env_fallback_for_empty() -> None:
    assert parse_bool_env(None, True) is True
    assert parse_bool_env(None, False) is False
    assert parse_bool_env("", True) is True
    assert parse_bool_env("   ", False) is False


def test_parse_bool_env_truthy_falsy() -> None:
    for v in ("true", "TRUE", "1", "on", "yes", " Yes "):
        assert parse_bool_env(v, False) is True, v
    for v in ("false", "FALSE", "0", "off", "no", " No "):
        assert parse_bool_env(v, True) is False, v


def test_parse_bool_env_unknown_falls_back() -> None:
    assert parse_bool_env("maybe", True) is True
    assert parse_bool_env("maybe", False) is False


def test_parse_ms_env() -> None:
    assert parse_ms_env(None, 100) == 100
    assert parse_ms_env("5000", 100) == 5000
    assert parse_ms_env("nope", 100) == 100
    assert parse_ms_env("0", 100) == 100


# ---------------------------------------------------------------------------
# write_cycle_progress_atomic
# ---------------------------------------------------------------------------


def test_write_cycle_progress_atomic_complete_json(tmp_path: Path) -> None:
    path = tmp_path / "cycle_progress.json"
    before = int(__import__("time").time() * 1000)
    ok = write_cycle_progress_atomic(
        path,
        {
            "pid": 12345,
            "outer_cycle": 5372,
            "inner_cycle": 17,
            "started_at": 1746543112000,
            "phase": "evolve.run",
        },
    )
    after = int(__import__("time").time() * 1000)
    assert ok is True
    assert path.exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["pid"] == 12345
    assert parsed["outer_cycle"] == 5372
    assert parsed["inner_cycle"] == 17
    assert parsed["started_at"] == 1746543112000
    assert parsed["phase"] == "evolve.run"
    assert isinstance(parsed["updated_at"], int)
    assert before <= parsed["updated_at"] <= after + 1000


def test_write_cycle_progress_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "cycle_progress.json"
    write_cycle_progress_atomic(
        path, {"pid": os.getpid(), "outer_cycle": 1, "phase": "sleep", "started_at": 100}
    )
    write_cycle_progress_atomic(
        path, {"pid": os.getpid(), "outer_cycle": 2, "phase": "evolve.run", "started_at": 200}
    )
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["phase"] == "evolve.run"
    assert parsed["outer_cycle"] == 2


def test_write_cycle_progress_no_tmp_leftovers(tmp_path: Path) -> None:
    path = tmp_path / "cycle_progress.json"
    write_cycle_progress_atomic(
        path,
        {
            "pid": os.getpid(),
            "outer_cycle": 2,
            "inner_cycle": 2,
            "started_at": 200,
            "phase": "evolve.run",
        },
    )
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_write_cycle_progress_unwritable_returns_false(tmp_path: Path) -> None:
    # File as parent path → mkdir of nested target fails or write fails.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    bad = blocker / "sub" / "cycle_progress.json"
    ok = write_cycle_progress_atomic(
        bad,
        {
            "pid": os.getpid(),
            "outer_cycle": 1,
            "inner_cycle": 1,
            "started_at": 1,
            "phase": "evolve.run",
        },
    )
    assert ok is False
    assert not bad.exists()


# ---------------------------------------------------------------------------
# spawn_replacement_process
# ---------------------------------------------------------------------------


def test_spawn_windows_default_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_SUICIDE_WINDOWS", raising=False)
    result = spawn_replacement_process(
        reason="unit-test",
        args=["--loop"],
        log_path="/no/such/log/should-not-be-touched.log",
        platform="win32",
    )
    assert result["spawned"] is False
    assert result["reason"] == "windows_default_skip"


def test_spawn_windows_explicit_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_SUICIDE_WINDOWS", "false")
    result = spawn_replacement_process(
        reason="unit-test",
        args=["--loop"],
        log_path="/no/such/log/should-not-be-touched.log",
        platform="win32",
    )
    assert result["spawned"] is False
    assert result["reason"] == "windows_default_skip"


def test_spawn_windows_opt_in_reaches_spawn_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_SUICIDE_WINDOWS", "true")
    # File-as-directory makes open/mkdir fail on every platform.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    result = spawn_replacement_process(
        reason="unit-test",
        args=["--loop"],
        log_path=blocker / "child" / "log.txt",
        platform="win32",
    )
    assert result["spawned"] is False
    assert result["reason"] == "spawn_error"
    assert result.get("error") is not None


def test_spawn_linux_skips_windows_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_SUICIDE_WINDOWS", raising=False)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    result = spawn_replacement_process(
        reason="unit-test",
        args=["--loop"],
        log_path=blocker / "child" / "log.txt",
        platform="linux",
    )
    assert result["spawned"] is False
    assert result["reason"] == "spawn_error"


def test_spawn_darwin_skips_windows_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_SUICIDE_WINDOWS", raising=False)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    result = spawn_replacement_process(
        reason="unit-test",
        args=["--loop"],
        log_path=blocker / "child" / "log.txt",
        platform="darwin",
    )
    assert result["spawned"] is False
    assert result["reason"] == "spawn_error"


# ---------------------------------------------------------------------------
# handle_cycle_timeout
# ---------------------------------------------------------------------------


def test_handle_cycle_timeout_continue_when_suicide_off(tmp_path: Path) -> None:
    path = tmp_path / "cycle_progress.json"
    err = CycleTimeoutError(1000, "evolve.run", 1)
    action = handle_cycle_timeout(
        error=err,
        cycle_progress_path=path,
        progress_fields={"pid": 1, "outer_cycle": 1, "started_at": 1},
        suicide_enabled_flag=False,
        spawn_replacement_fn=lambda **_: {"spawned": False},
    )
    assert action["action"] == "continue"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["phase"] == "cycle_timeout_nonfatal"


def test_handle_cycle_timeout_respawn_when_suicide_on(tmp_path: Path) -> None:
    path = tmp_path / "cycle_progress.json"
    calls: list[dict] = []

    def fake_spawn(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"spawned": True}

    err = CycleTimeoutError(1000, "evolve.run", 2)
    action = handle_cycle_timeout(
        error=err,
        cycle_progress_path=path,
        progress_fields={"pid": 1, "outer_cycle": 2, "started_at": 1},
        suicide_enabled_flag=True,
        args=["--loop"],
        spawn_replacement_fn=fake_spawn,
    )
    assert action["action"] == "respawn"
    assert calls and calls[0]["reason"] == "cycle_hard_timeout"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["phase"] == "cycle_timeout_respawn"


def test_runner_wires_timeout_helpers() -> None:
    """Static smoke: runner imports the cycle-control API (structure guard)."""
    import inspect

    from evolver.evolve import runner as runner_mod

    src = inspect.getsource(runner_mod.run_loop)
    assert "cycle_timeout_enabled" in src
    assert "CycleTimeoutError" in src
    assert "handle_cycle_timeout" in src
    assert "spawn_replacement_process" in src
    assert "wait_for" in src or "asyncio.wait_for" in src
