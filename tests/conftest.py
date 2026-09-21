"""Shared pytest fixtures."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _neutral_fitness_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    """S26: the fitness cascade is the DEFAULT solidify validation path.

    Sandboxed test workspaces have no src/tests for ruff/mypy/pytest to
    inspect, so swap in a workspace-neutral command set globally. Tests that
    exercise cascade mechanics monkeypatch FITNESS_CASCADE_COMMANDS again;
    legacy-path tests set enable_fitness_cascade=False explicitly.
    """
    from evolver.gep import solidify as solidify_mod

    neutral: list[dict[str, Any]] = [
        {"command": [sys.executable, "-c", "print('ok')"]},
    ]
    monkeypatch.setattr(solidify_mod, "FITNESS_CASCADE_COMMANDS", neutral)


@pytest.fixture(autouse=True)
def _restore_feature_flags() -> Iterator[None]:
    """Round-26 (DEBUG #37b): set_flag(persist=False) mutates a process-wide
    in-memory flag cache with NO undo — a test leaving enable_fitness_cascade
    off silently rerouted later tests onto the legacy solidify path (a wiki
    shadow-rejection test lost its entry; latent until the two files ran
    adjacently). Snapshot the cache around every test: for flags what
    monkeypatch is for environment variables."""
    from evolver.gep import feature_flags as ff

    # test-side snapshot of the private in-memory flag cache
    with ff._lock:
        snapshot = dict(ff._disk_flags)
    yield
    with ff._lock:
        ff._disk_flags = snapshot
        ff._disk_flags_loaded_at = ff.time.monotonic()


@pytest.fixture(autouse=True)
def _isolate_hub_endpoint_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round-48 (DEBUG #37 family, preventive): hub_health sticky state is
    PRODUCTION runtime state. An unisolated test hitting a 404 failure path
    would write the counter into the in-repo evolution dir; three such writes
    flip endpoint_sticky() and make OTHER unisolated tests fast-fail through
    the hub_client preflight instead of their own mocks — the same shape as
    the soak-route leak (#44). Redirect the state path per-test,
    unconditionally: a conditional skip would race the test's own
    monkeypatch.setenv ordering."""
    from evolver.gep import hub_health

    per_test = tmp_path / "hub_endpoint_state.json"
    monkeypatch.setattr(hub_health, "state_path", lambda: per_test)


@pytest.fixture(autouse=True)
def _isolate_sniffer_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round-54 (DEBUG #37 family): conversation_sniffer state is PRODUCTION
    runtime state — enforce-mode sniffs with candidates arm the cooldown and
    _write_state unconditionally. An unisolated test calling try_sniff with
    real evidence wrote `last_sniff_ts` into the in-repo evolution dir
    (caught live: the file's ts incremented across a test run). Redirect
    unconditionally, same doctrine as the hub-state fixture."""
    from evolver.gep import conversation_sniffer as cs

    monkeypatch.setattr(cs, "_state_path", lambda: tmp_path / "conv_sniffer_state.json")


@pytest.fixture(autouse=True, scope="session")
def _shield_ambient_load() -> Iterator[None]:
    """Full-cycle tests (run/cli/integration) must not preflight-abort on
    ambient host load. test_guards.py pins EVOLVE_LOAD_MAX=0.01 itself to
    cover the load-abort path deterministically."""
    mp = pytest.MonkeyPatch()
    mp.setenv("EVOLVE_LOAD_MAX", "999")
    yield
    mp.undo()


@pytest.fixture(autouse=True, scope="session")
def _production_wiki_tripwire() -> Iterator[None]:
    """Round-26 (DEBUG #37): a test once drove the real cascade-failure path
    without env isolation and appended its fixture rejections ("gene-1") to
    the PRODUCTION wiki — 128 of 161 skill-impact entries were that noise by
    the time it was caught. The suite must never write runtime state outside
    its sandboxes: snapshot the real wiki's entry count at session start and
    assert it unchanged at teardown. Redirect is a deliberate non-goal —
    env-driven wiki tests (test_wiki.py) manage their own paths."""
    import os

    if os.environ.get("EVOLUTION_DIR"):
        # An outer harness already isolated the evolution dir.
        yield
        return
    from evolver.gep.paths import get_evolution_dir

    path = get_evolution_dir() / "wiki" / "skill-impact.md"

    def _entries() -> int:
        if not path.is_file():
            return 0
        return sum(
            1
            for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.startswith("## ")
        )

    before = _entries()
    yield
    after = _entries()
    assert after == before, (
        f"production wiki gained {after - before} entr{'y' if after - before == 1 else 'ies'} "
        "during the test session — a test wrote runtime state without isolating "
        "its wiki/evolution-dir path (request temp_workspace or monkeypatch the writer)"
    )


@pytest.fixture(autouse=True, scope="session")
def _phantom_abort_snapshot_tripwire() -> Iterator[None]:
    """Round-28 (DEBUG #39): a full-cycle test once aborted through the REAL
    runner and persisted its fixture reason ("test abort") as the production
    preflight-abort snapshot — every later evolution cycle then injected
    phantom preflight_abort signals and repair bias. The abort path returns
    before the end-of-cycle clear, so an unisolated test's snapshot survives
    the session. The daemon legitimately writes real abort reasons (load /
    lock / release-window), so existence alone cannot trip — only a snapshot
    whose reason is a known test fixture string does (zero false positives)."""
    import json
    import os

    if os.environ.get("EVOLUTION_DIR"):
        # An outer harness already isolated the evolution dir.
        yield
        return
    from evolver.gep.paths import get_evolution_dir

    path = get_evolution_dir() / "autopoiesis_preflight_abort.json"

    def _reason() -> str | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None
        return str(data.get("reason") or "").strip() if isinstance(data, dict) else None

    yield
    final_reason = _reason()
    assert final_reason != "test abort", (
        "production preflight-abort snapshot carries the test fixture reason "
        "'test abort' — a test persisted an abort through the real runner "
        "without isolating its evolution dir (request temp_workspace)"
    )


@pytest.fixture(autouse=True, scope="session")
def _production_gene_store_tripwire() -> Iterator[None]:
    """Round-35 (DEBUG #41): an unisolated sync test installed its fixture
    gene ("g1") into the PRODUCTION genes.jsonl overlay on every full-suite
    run — 120 entries by the time it was caught, one loading as a live
    library member. The suite must never mutate the real asset store:
    snapshot the overlay line counts (genes + capsules) at session start and
    assert them unchanged at teardown. A concurrent distill from another
    process during the session would false-positive — same accepted risk as
    the wiki tripwire; the daemon does not distill."""
    import os

    if os.environ.get("EVOLUTION_DIR") or os.environ.get("GEP_ASSETS_DIR"):
        # An outer harness already isolated (or explicitly targeted) the store.
        yield
        return
    from evolver.gep.paths import get_gep_assets_dir

    store = get_gep_assets_dir()

    def _counts() -> tuple[int, int]:
        def lines(name: str) -> int:
            path = store / name
            if not path.is_file():
                return 0
            return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))

        return lines("genes.jsonl"), lines("capsules.jsonl")

    before = _counts()
    yield
    after = _counts()
    assert after == before, (
        f"production gene store changed during the test session: genes/capsules "
        f"{before} -> {after} — a test installed assets without isolating "
        "GEP_ASSETS_DIR (request temp_workspace)"
    )


@pytest.fixture
def temp_workspace(monkeypatch: pytest.MonkeyPatch) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
        monkeypatch.setenv("MEMORY_DIR", str(ws / "memory"))
        monkeypatch.setenv("EVOLUTION_DIR", str(ws / "memory" / "evolution"))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(ws / ".evolver" / "gep"))
        monkeypatch.setenv("EVOLVER_LOGS_DIR", str(ws / "logs"))
        monkeypatch.setenv("EVOLVER_SETTINGS_DIR", str(ws / ".evolver_settings"))
        monkeypatch.setenv("EVOLVER_HOME", str(ws / ".evomap"))
        yield ws
