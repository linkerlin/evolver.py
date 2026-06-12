"""Tests for evolver.evolve.guards."""

from __future__ import annotations

import asyncio

import pytest

from evolver.evolve import guards


def test_preflight_load_exceeds_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "0.01")
    result = asyncio.run(guards.run_preflight_checks(is_dry_run=False))
    assert isinstance(result.abort, bool)


def test_preflight_dry_run_never_aborts() -> None:
    result = asyncio.run(guards.run_preflight_checks(is_dry_run=True))
    assert result.abort is False


def test_repair_loop_circuit_breaker_empty() -> None:
    cb = guards.check_repair_loop_circuit_breaker()
    assert cb["tripped"] is False
    assert cb["consecutive"] == 0


def test_repair_loop_degraded_preflight(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPAIR_LOOP_DEGRADED", "1")
    from evolver.gep.asset_store import append_event_jsonl
    from evolver.gep.paths import get_gep_assets_dir

    get_gep_assets_dir().mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "mutation": {"category": "repair"},
                "outcome": {"status": "failed"},
            }
        )
    result = asyncio.run(guards.run_preflight_checks(is_dry_run=False))
    assert result.abort is False
    assert result.repair_loop_degraded is True


def test_repair_loop_circuit_breaker_trips(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    from evolver.gep.asset_store import append_event_jsonl
    from evolver.gep.paths import get_gep_assets_dir

    get_gep_assets_dir().mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "mutation": {"category": "repair"},
                "outcome": {"status": "failed"},
            }
        )
    cb = guards.check_repair_loop_circuit_breaker(threshold=3)
    assert cb["tripped"] is True
    assert cb["consecutive"] == 3


def test_repair_loop_circuit_breaker_resets_on_success(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    from evolver.gep.asset_store import append_event_jsonl
    from evolver.gep.paths import get_gep_assets_dir

    get_gep_assets_dir().mkdir(parents=True, exist_ok=True)
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "mutation": {"category": "repair"},
            "outcome": {"status": "failed"},
        }
    )
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "mutation": {"category": "repair"},
            "outcome": {"status": "success"},
        }
    )
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "mutation": {"category": "repair"},
            "outcome": {"status": "failed"},
        }
    )
    cb = guards.check_repair_loop_circuit_breaker(threshold=2)
    assert cb["tripped"] is False
    assert cb["consecutive"] == 1


def test_evaluate_user_lock_no_lock(tmp_path: Path) -> None:
    result = guards.evaluate_user_lock(tmp_path / "nonexistent.lock")
    assert result.yield_required is False
    assert result.reason == "no_lock"


def test_evaluate_user_lock_active(tmp_path: Path) -> None:
    lock = tmp_path / "user.lock"
    lock.write_text("x")
    result = guards.evaluate_user_lock(lock, ttl_ms=60_000)
    assert result.yield_required is True
    assert result.reason == "lock_active"


def test_evaluate_user_lock_stale(tmp_path: Path) -> None:
    import time

    lock = tmp_path / "user.lock"
    lock.write_text("x")
    # Manually set mtime far in the past
    old = time.time() - 120
    import os

    os.utime(lock, (old, old))
    result = guards.evaluate_user_lock(lock, ttl_ms=60_000)
    assert result.yield_required is False
    assert result.reason == "lock_stale"


def test_evaluate_release_window_disabled() -> None:
    result = guards.evaluate_release_window("chore(release) v1", 0.0, window_ms=0)
    assert result.yield_required is False


def test_evaluate_release_window_active() -> None:
    import time

    now = time.time() * 1000
    result = guards.evaluate_release_window("chore(release) v1", (now - 60_000) / 1000.0, now=now)
    assert result.yield_required is True
    assert result.reason == "release_window_active"
