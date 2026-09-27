"""Paired evolution session - every illegal terminal state must be refused.

Charter completion criterion: 演进方案.md §5.1. ``EVOLUTION_DIR`` is pointed
at tmp, so nothing touches the real soak root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.evolution_session import (
    ACCEPTED,
    DEFAULT_MAX_ROUNDS,
    INCOMPLETE,
    RUNNING,
    EvolutionBudgetExhaustedError,
    EvolutionError,
    EvolutionSession,
    EvolutionTerminalError,
)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "evolution"
    root.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(root))
    return root


@pytest.fixture()
def session(session_root: Path) -> EvolutionSession:
    ev = EvolutionSession()
    ev.start_run("parent-snapshot-aaa")
    return ev


# ---- 开会话与预算冻结 -----------------------------------------------------


def test_start_freezes_default_budget(session: EvolutionSession) -> None:
    assert session.run["budget"]["max_rounds"] == DEFAULT_MAX_ROUNDS
    assert session.status == RUNNING
    assert session.run["parent"] == "parent-snapshot-aaa"


def test_start_refuses_while_a_run_is_open(session: EvolutionSession) -> None:
    with pytest.raises(EvolutionError, match="still running"):
        EvolutionSession().start_run("another-parent")


def test_start_requires_parent(session_root: Path) -> None:
    with pytest.raises(ValueError):
        EvolutionSession().start_run("")


# ---- Reject 不结束会话 ----------------------------------------------------


def test_reject_keeps_the_session_running(session: EvolutionSession) -> None:
    session.begin_round("hypothesis A", "cand-1")
    session.record_round(decision="reject", notes="flat on val")

    assert session.status == RUNNING
    assert session.rejected_count() == 1
    assert session.must_continue() is True


def test_record_round_refuses_non_reject(session: EvolutionSession) -> None:
    session.begin_round("hypothesis A", "cand-1")
    with pytest.raises(ValueError, match="only records rejects"):
        session.record_round(decision="accept")


def test_rejects_accumulate_across_rounds(session: EvolutionSession) -> None:
    for index in range(3):
        session.begin_round(f"hypothesis {index}", f"cand-{index}")
        session.record_round(decision="reject")
    assert session.rejected_count() == 3
    assert session.status == RUNNING


# ---- 预算耗尽自动封口 -----------------------------------------------------


def test_budget_exhausted_closes_the_session(session: EvolutionSession) -> None:
    for index in range(DEFAULT_MAX_ROUNDS):
        session.begin_round(f"h{index}", f"cand-{index}")
        session.record_round(decision="reject")

    with pytest.raises(EvolutionBudgetExhaustedError):
        session.begin_round("one too many", "cand-overflow")

    assert session.status == INCOMPLETE
    assert session.run["end_reason"] == "budget_exhausted"


def test_extended_budget_is_spent_before_closing(session: EvolutionSession) -> None:
    session.extend_budget(DEFAULT_MAX_ROUNDS + 2, confirmed_by="stepbrother")
    for index in range(DEFAULT_MAX_ROUNDS + 2):
        session.begin_round(f"h{index}", f"cand-{index}")
        session.record_round(decision="reject")

    with pytest.raises(EvolutionBudgetExhaustedError):
        session.begin_round("overflow", "cand-x")
    assert session.status == INCOMPLETE


# ---- 加预算只有人能做 -----------------------------------------------------


def test_host_cannot_extend_budget(session: EvolutionSession) -> None:
    # "host-agent" is the actor name the swarm loop actually uses — it must
    # be on the blacklist too, not just the bare "host".
    for actor in (
        "host",
        "host-agent",
        "host_agent",
        "agent",
        "swarm",
        "loop",
        "evolver",
    ):
        with pytest.raises(EvolutionError, match="human-only"):
            session.extend_budget(99, confirmed_by=actor)


def test_extend_budget_needs_a_named_human(session: EvolutionSession) -> None:
    with pytest.raises(EvolutionError, match="confirmed_by"):
        session.extend_budget(99, confirmed_by="")


def test_extend_budget_must_increase(session: EvolutionSession) -> None:
    with pytest.raises(ValueError, match="must increase"):
        session.extend_budget(DEFAULT_MAX_ROUNDS, confirmed_by="stepbrother")
    with pytest.raises(ValueError, match="must increase"):
        session.extend_budget(2, confirmed_by="stepbrother")


def test_budget_history_records_every_raise(session: EvolutionSession) -> None:
    session.extend_budget(10, confirmed_by="stepbrother")
    session.extend_budget(12, confirmed_by="stepbrother")
    history = session.run["budget_history"]
    assert [entry["max_rounds"] for entry in history] == [8, 10, 12]
    assert history[-1]["confirmed_by"] == "stepbrother"


# ---- 判断性停止要有足够的 Reject -------------------------------------------


@pytest.mark.parametrize("reason", ["missing_data", "unreliable_evaluation", "external_block"])
def test_judgment_stop_needs_two_rejects(session: EvolutionSession, reason: str) -> None:
    with pytest.raises(EvolutionError, match="rejected candidates are required"):
        session.mark_incomplete(reason)

    session.begin_round("h0", "cand-0")
    session.record_round(decision="reject")
    with pytest.raises(EvolutionError, match="rejected candidates are required"):
        session.mark_incomplete(reason)

    session.begin_round("h1", "cand-1")
    session.record_round(decision="reject")
    session.mark_incomplete(reason)
    assert session.status == INCOMPLETE
    assert session.run["end_reason"] == reason


@pytest.mark.parametrize("reason", ["user_interrupted", "missing_permissions"])
def test_immediate_stop_needs_no_rejects(session: EvolutionSession, reason: str) -> None:
    session.mark_incomplete(reason)
    assert session.status == INCOMPLETE


def test_stagnation_is_not_a_stop_reason(session: EvolutionSession) -> None:
    with pytest.raises(ValueError, match="incomplete reason must be one of"):
        session.mark_incomplete("stagnation")
    with pytest.raises(ValueError, match="incomplete reason must be one of"):
        session.mark_incomplete("reject")


def test_budget_exhausted_cannot_be_claimed_early(session: EvolutionSession) -> None:
    with pytest.raises(EvolutionError, match="budget has not been spent"):
        session.mark_incomplete("budget_exhausted")


# ---- 终态不可再动 ---------------------------------------------------------


def test_terminal_session_cannot_be_resumed(session: EvolutionSession) -> None:
    session.mark_incomplete("user_interrupted")
    with pytest.raises(EvolutionTerminalError, match="already ended"):
        EvolutionSession().resume()


def test_terminal_session_refuses_rounds_and_decisions(
    session: EvolutionSession,
) -> None:
    session.mark_incomplete("user_interrupted")
    with pytest.raises(EvolutionTerminalError):
        session.begin_round("h", "cand")
    with pytest.raises(EvolutionTerminalError):
        session.record_round(decision="reject")
    with pytest.raises(EvolutionTerminalError):
        session.accept()
    with pytest.raises(EvolutionTerminalError):
        session.mark_incomplete("user_interrupted")


def test_finalize_refuses_a_running_session(session: EvolutionSession) -> None:
    with pytest.raises(EvolutionError, match="still running"):
        session.finalize()


def test_finalize_accepts_a_terminal_session(session: EvolutionSession) -> None:
    session.mark_incomplete("user_interrupted")
    assert session.finalize()["status"] == INCOMPLETE


# ---- Accept --------------------------------------------------------------


def test_accept_without_candidate_is_refused(session: EvolutionSession) -> None:
    with pytest.raises(EvolutionError, match="No Candidate"):
        session.accept()


def test_accept_publishes_and_closes(session: EvolutionSession) -> None:
    session.begin_round("h", "cand-1")
    published = session.accept(
        gate=lambda run: {"accept": True, "reason": "strict_improvement"},
        publish=lambda candidate: f"ontology_{candidate}",
    )

    assert published == "ontology_cand-1"
    assert session.status == ACCEPTED
    assert session.run["accepted_ref"] == "ontology_cand-1"


def test_bare_accept_is_refused_without_a_gate_record(session: EvolutionSession) -> None:
    """§5.2 — the session's Accept is an echo of a real gate verdict.

    ``evolver session accept`` runs with no injected gate, so it reads the
    decision solidify persisted. Without one (or with a refusing one) the
    Accept is a claim, not a measurement, and must be refused.
    """
    session.begin_round("h", "cand-1")
    with pytest.raises(EvolutionError, match="did not pass the publication gate"):
        session.accept()
    assert session.status == RUNNING

    # A persisted refusal is just as binding as a missing record.
    session.record_gate_decision({"accept": False, "reason": "flat"})
    with pytest.raises(EvolutionError, match="did not pass the publication gate"):
        session.accept()
    assert session.status == RUNNING


def test_accept_falls_back_to_the_persisted_gate_record(session: EvolutionSession) -> None:
    """solidify wrote an accept:true verdict — the session may Accept."""
    session.begin_round("h", "cand-1")
    session.record_gate_decision({"accept": True, "reason": "strict_improvement"})
    published = session.accept(publish=lambda candidate: f"lib_{candidate}")
    assert published == "lib_cand-1"
    assert session.run["gate"]["reason"] == "strict_improvement"


def test_gate_decision_persists_next_to_the_run(
    session: EvolutionSession, session_root: Path
) -> None:
    session.begin_round("h", "cand-1")
    session.record_gate_decision({"accept": False, "reason": "no_baseline"})
    recorded = session.pending_gate()
    assert recorded is not None and recorded["accept"] is False
    gate_file = session_root / "sessions" / "run_1" / "gate.json"
    assert gate_file.is_file()


def test_accept_is_refused_when_the_gate_says_no(session: EvolutionSession) -> None:
    session.begin_round("h", "cand-1")
    with pytest.raises(EvolutionError, match="did not pass the publication gate"):
        session.accept(gate=lambda run: {"accept": False, "protocol": "ground_truth"})
    assert session.status == RUNNING


def test_accept_records_the_gate_verdict(session: EvolutionSession) -> None:
    session.begin_round("h", "cand-1")
    session.accept(gate=lambda run: {"accept": True, "delta": 0.25})
    assert session.run["gate"]["delta"] == 0.25


# ---- 落盘 -----------------------------------------------------------------


def test_run_json_and_rounds_jsonl_are_persisted(
    session: EvolutionSession, session_root: Path
) -> None:
    session.begin_round("h0", "cand-0")
    session.record_round(decision="reject", metrics={"val": 0.5})
    session.begin_round("h1", "cand-1")
    session.accept(gate=lambda run: {"accept": True, "reason": "strict_improvement"})

    run_file = session_root / "sessions" / "run_1" / "run.json"
    rounds_file = session_root / "sessions" / "run_1" / "rounds.jsonl"
    assert json.loads(run_file.read_text(encoding="utf-8"))["status"] == ACCEPTED
    lines = [
        json.loads(line)
        for line in rounds_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["decision"] == "reject"
    assert lines[0]["metrics"] == {"val": 0.5}


def test_evaluations_are_written_under_the_run(
    session: EvolutionSession, session_root: Path
) -> None:
    session.begin_round("h0", "cand-0")
    path = session.record_evaluation(
        "cand-0",
        {
            "metrics": {"val": 0.75},
            "cases": ["t1", "t2"],
            "gate_input": {"protocol": "ground_truth"},
        },
        role="candidate",
    )
    assert path.is_file()
    assert path.parent.name == "evaluations"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["round"] == 1
    assert payload["gate_input"]["protocol"] == "ground_truth"


def test_sessions_live_outside_the_product_repo(
    session: EvolutionSession, session_root: Path
) -> None:
    """Session dirs must sit under EVOLUTION_DIR, never inside the product repo."""
    assert session.run_dir.parent == session_root / "sessions"
    assert session_root != Path(__file__).resolve().parents[1]
