"""Tests for evolver.solo — constrained-wild offline mode (G10.2).

Port of ``evolver/test/soloMode.test.js``. Solo hard-cuts network/validator/ATP
with no escape valve and restricts git to local-only operations.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from evolver.config import resolve_hub_url
from evolver.evolve import post_cycle
from evolver.gep import git_ops
from evolver.gep.validator import start_validator
from evolver.solo import breaker, print_solo_banner
from evolver.solo.git_guard import NETWORK_GIT_SUBCOMMANDS, guard_git_subcommand


@pytest.fixture(autouse=True)
def _isolate_solo_env() -> None:
    """Snapshot/restore every env solo mutates (activate writes os.environ
    directly to enforce the no-escape-valve override)."""
    touched = (
        "EVOLVER_SOLO",
        "A2A_HUB_URL",
        "EVOMAP_HUB_URL",
        "EVOLVER_DEFAULT_HUB_URL",
        "EVOLVER_VALIDATOR_ENABLED",
        "EVOLVER_ATP",
        "EVOLVER_ATP_AUTOBUY",
    )
    saved = {k: os.environ.get(k) for k in touched}
    breaker.deactivate()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    breaker.deactivate()


# ---------------------------------------------------------------------------
# breaker: no escape valve
# ---------------------------------------------------------------------------
def test_activate_sets_solo_flag_and_forces_services_off() -> None:
    breaker.activate()
    assert breaker.is_solo_active() is True
    assert os.environ["EVOLVER_VALIDATOR_ENABLED"] == "0"
    assert os.environ["EVOLVER_ATP"] == "off"
    assert os.environ["EVOLVER_ATP_AUTOBUY"] == "off"


def test_no_escape_valve_hub_url_ignored_even_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # User explicitly provides a hub URL — solo must still cut it.
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")  # allow http for the test
    monkeypatch.setenv("A2A_HUB_URL", "http://dead.invalid")
    monkeypatch.setenv("EVOMAP_HUB_URL", "http://dead.invalid")
    assert resolve_hub_url() == "http://dead.invalid"  # before solo
    breaker.activate()
    assert resolve_hub_url() == ""  # after solo: no escape valve


def test_deactivate_restores_non_solo_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    breaker.activate()
    assert resolve_hub_url() == ""
    breaker.deactivate()
    # deactivate lifts the solo force-cut (it does not restore clobbered envs):
    # a freshly-set hub URL is honoured again.
    monkeypatch.setenv("A2A_HUB_URL", "http://hub.example")
    assert resolve_hub_url() == "http://hub.example"


# ---------------------------------------------------------------------------
# validator cut
# ---------------------------------------------------------------------------
def test_start_validator_returns_none_under_solo() -> None:
    breaker.activate()
    assert start_validator() is None


# ---------------------------------------------------------------------------
# git guard: local-git-only
# ---------------------------------------------------------------------------
def test_network_git_subcommands_blocked_under_solo() -> None:
    breaker.activate()
    for sub in NETWORK_GIT_SUBCOMMANDS:
        assert guard_git_subcommand(sub) is not None, sub


def test_local_git_subcommands_allowed_under_solo() -> None:
    breaker.activate()
    for sub in ("status", "diff", "stash", "log", "add"):
        assert guard_git_subcommand(sub) is None, sub


def test_run_cmd_refuses_network_git_under_solo(tmp_path: Path) -> None:
    breaker.activate()
    with pytest.raises(RuntimeError, match="solo: network git 'fetch' blocked"):
        git_ops.run_cmd(["fetch", "origin"], cwd=tmp_path)


def test_run_cmd_allows_local_git_without_solo(tmp_path: Path) -> None:
    # Not solo: a local command must run normally (no guard interference).
    assert git_ops.run_cmd(["init", "-q"], cwd=tmp_path) == ""


# ---------------------------------------------------------------------------
# post_cycle ATP cut
# ---------------------------------------------------------------------------
async def test_post_cycle_skips_atp_under_solo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo must cut ATP auto-buyer and task pickup even if the flag is on."""
    # Force the feature flag on AND seed consent so the only thing preventing
    # ATP spend is the solo guard.
    monkeypatch.setattr("evolver.gep.feature_flags.is_enabled", lambda _name: True, raising=False)

    calls: list[str] = []
    monkeypatch.setattr(
        "evolver.atp.auto_buyer.get_consent",
        lambda: {"enabled": True},
        raising=False,
    )

    async def _boom_run_tick(_signals):
        calls.append("run_tick")
        return {"placed": 0}

    monkeypatch.setattr("evolver.atp.auto_buyer.run_tick", _boom_run_tick, raising=False)

    async def _boom_pick():
        calls.append("pick_one")

    monkeypatch.setattr("evolver.atp.atp_task_pickup.pick_one", _boom_pick, raising=False)

    breaker.activate()
    await post_cycle.run_post_cycle_hooks({"signals": ["log_error"]})
    assert calls == []  # neither ATP path ran under solo

    breaker.deactivate()
    await post_cycle.run_post_cycle_hooks({"signals": ["log_error"]})
    assert "run_tick" in calls  # ATP runs again once solo is off


# ---------------------------------------------------------------------------
# banner
# ---------------------------------------------------------------------------
def test_banner_contains_required_fragments(capsys: pytest.CaptureFixture[str]) -> None:
    print_solo_banner()
    out = capsys.readouterr().out
    assert "受约束的野性模式已启动" in out
    assert "断网" in out
    assert "禁ATP" in out
    assert "仅本机git可追踪" in out


# ---------------------------------------------------------------------------
# subprocess smoke: --solo routes into loop, prints banner, exits clean
# ---------------------------------------------------------------------------
def _solo_env(tmp: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "A2A_HUB_URL": "http://dead.invalid",  # solo must override this
            "EVOMAP_HUB_URL": "",
            "EVOLVER_REPO_ROOT": str(tmp),
            "EVOLVER_LOCK_DIR": str(tmp),
            "EVOLVER_SETTINGS_DIR": str(tmp / ".evolver-settings"),
            "EVOLVER_NO_PARENT_GIT": "1",
            "GEP_ASSETS_DIR": str(tmp / "gep"),
            "MEMORY_DIR": str(tmp / "memory"),
            "EVOLUTION_DIR": str(tmp / "memory" / "evolution"),
            "EVOMAP_PROXY": "0",
            "EVOMAP_PROXY_AUTO_INJECT": "off",
            "EVOLVER_VALIDATOR_ENABLED": "true",  # solo must cut it
            "EVOLVER_ATP": "on",
            "EVOLVER_ATP_AUTOBUY": "on",  # solo must cut it
            "EVOLVER_MAX_CYCLES_PER_PROCESS": "1",
            "EVOLVER_IDLE_FETCH_INTERVAL_MS": "1",
        }
    )
    return env


def test_solo_cli_routes_into_loop_and_cuts_services(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init", "-q"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    proc = subprocess.run(
        [sys.executable, "-m", "evolver", "--solo"],
        cwd=repo,
        env=_solo_env(repo),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = proc.stdout + proc.stderr

    # Banner present (routes into loop + solo banner).
    assert "受约束的野性模式已启动" in combined
    assert "断网" in combined
    assert "禁ATP" in combined
    # No escape valve: solo overrode the dead hub URL, so no service started.
    assert "startHeartbeat" not in combined
    assert "[ValidatorDaemon] Started" not in combined
    assert "[ATP-AutoBuyer] Started" not in combined
    assert "ATP auto-spend is ON" not in combined
    # Clean exit, no uncaught tracebacks.
    assert proc.returncode == 0, combined
    assert "Traceback (most recent call last)" not in combined, combined[:800]
