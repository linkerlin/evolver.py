"""FSM pending-run safety invariants (replaces legacy 17-flag redirect maze).

Under 算子即基因 P1-1:
- When a run is pending on disk (``ACTIVE_RUN``), ``evolve_begin`` is physically
  hidden from ``tools/list`` and hard-blocked at ``tools/call``;
- Read-only smoke calls (``evolve_status``, ``run_lens``) inspect the workspace
  without clobbering or settling the pending run;
- ``pending_tick_redirects.json`` is never written, and none of the 17 legacy
  whack-a-mole boolean flags appear in responses.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

VOIDED_REDIRECT_FLAGS: frozenset[str] = frozenset(
    {
        "gate_soft_continue",
        "tick_again",
        "session_not_failed",
        "loop_fuse",
        "redirect_reason",
        "preserve_pending",
        "abandon_run",
        "action_required",
        "soft_gap",
        "tick_closed",
        "readonly_smoke",
    }
)


@pytest.fixture
def isolated_swarm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVE_LOAD_MAX", "999")
    return tmp_path


def _write_pending(run_id: str = "run_pending_smoke") -> None:
    from evolver.gep.solidify import write_state_for_solidify

    write_state_for_solidify(
        {
            "run_id": run_id,
            "signals": ["log_error"],
            "selected_gene_id": "g_smoke",
            "mutation": {"id": "m_smoke", "validation": []},
        }
    )


def test_active_run_hides_evolve_begin_and_blocks_reentry(isolated_swarm_env: Path) -> None:
    from evolver.mcp_server import build_server
    from evolver.swarm import evolve_begin, fsm_state

    _write_pending("run_active_guard")
    assert fsm_state() == "ACTIVE_RUN"

    server = build_server()
    visible = {t.name for t in asyncio.run(server.list_tools())}
    assert "evolve_begin" not in visible
    assert {"run_lens", "evolve_settle", "evolve_status"} <= visible

    blocked = asyncio.run(evolve_begin(hypothesis="attempt reentry"))
    assert blocked["ok"] is False
    assert blocked["error"] == "fsm_state_mismatch"
    assert blocked["fsm_state"] == "ACTIVE_RUN"
    assert blocked["active_run_id"] == "run_active_guard"
    assert VOIDED_REDIRECT_FLAGS.isdisjoint(blocked.keys())
    assert not (isolated_swarm_env / "evolution" / "pending_tick_redirects.json").exists()


def test_read_only_status_and_lens_preserve_pending_run(isolated_swarm_env: Path) -> None:
    from evolver.swarm import evolve_run_lens, evolve_status, fsm_state

    (isolated_swarm_env / "sample.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
    _write_pending("run_keep_me")

    st = evolve_status()
    assert st["ok"] is True
    assert st["fsm_state"] == "ACTIVE_RUN"
    assert st["active_run_id"] == "run_keep_me"
    assert st["next_action"] == "evolve_settle"
    assert VOIDED_REDIRECT_FLAGS.isdisjoint(st.keys())

    lens = evolve_run_lens("ast_hotspot", target="sample.py")
    assert lens["ok"] is True
    assert fsm_state() == "ACTIVE_RUN"
