"""Paired-session gate order inside solidify (演进方案.md §5.2, §5.3).

Completion criteria pinned here:

- **a missing hypothesis fails before the pack gate even runs** — otherwise a
  recordless round could be laundered into a publish by scoring well;
- **flat and unmeasured are rejections** (round-79 let both through);
- **a proposal carrying val material is refused**, not sanitised.

The pack gate is reached only when a usable hypothesis is on record.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate as gate_mod
from evolver.gep import git_ops, val_seal
from evolver.gep import hypothesis as hypothesis_mod
from evolver.gep import solidify as solidify_mod
from evolver.gep.acceptance import solidify_hook as hook_mod
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_git_repo(ws: Path) -> None:
    _git(ws, "init")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    (ws / "README.md").write_text("init\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_paired_gate",
        "selected_gene_id": "gene_paired_gate",
        "signals": ["test"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_paired_gate",
            "category": "repair",
            "validation": [],
        },
    }


@pytest.fixture
def git_ws(temp_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap-home"))
    monkeypatch.setattr(
        solidify_mod,
        "rollback_tracked",
        lambda **kw: git_ops.rollback_tracked(**{**kw, "cwd": temp_workspace}),
    )
    monkeypatch.setattr(hook_mod, "gate_for_solidify", lambda _r, _c: None)
    _init_git_repo(temp_workspace)
    return temp_workspace


def _pack_payload() -> dict[str, Any]:
    val: dict[str, Any] = {
        "id": "pair-{n}",
        "split": "val",
        "title": "paired probe {n}",
        "prompt": "Write the phrase from ledger.txt into answer.txt.",
        "sandbox": {"ledger.txt": "expected phrase: aurora\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": "aurora"},
    }
    train: dict[str, Any] = {
        "id": "pair-train-1",
        "split": "train",
        "title": "paired warmup",
        "prompt": "Warm up on the scratch note.",
        "sandbox": {"note.txt": "scratch\n"},
        "grader": {"type": "exact", "file": "answer.txt", "expected": "yes"},
    }
    return {
        "pack_version": 1,
        "tasks": [
            {**val, "id": "pair-1", "title": "paired probe 1"},
            {**val, "id": "pair-2", "title": "paired probe 2"},
            train,
        ],
    }


def _freeze_pack(git_ws: Path) -> Path:
    _ = git_ws
    path = gate_mod.frozen_pack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_pack_payload(), indent=2), encoding="utf-8")
    return path


def _solve(replicate: int, answers: dict[str, str]) -> None:
    root = gate_mod.sandbox_root(gate_mod.frozen_pack_path(), replicate=replicate)
    for task_id, answer in answers.items():
        sandbox = root / task_id
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "answer.txt").write_text(answer, encoding="utf-8")


def _good_hypothesis() -> dict[str, Any]:
    return {
        "hypothesis": "the executor misses the exclusion clause",
        "dimension": "content",
        "mechanism_family": "spec-literal",
        "target_hook": "dispatch prompt section 2",
        # A replayed observation, not a bare id: what was run, what changed.
        "mechanism_check": [
            {
                "id": "pair-train-1",
                "before": "the train task's answer lacked the exclusion clause",
                "after": "replayed after the change — the deliverable excludes it",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Gate order: hypothesis before pack
# ---------------------------------------------------------------------------


class TestHypothesisPrecedesPackGate:
    def test_missing_hypothesis_never_reaches_the_pack_gate(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of §5.3: no record, no measurement."""
        _freeze_pack(git_ws)
        hypothesis_mod.clear_hypothesis()

        calls: list[int] = []

        def _spy() -> dict[str, Any]:
            calls.append(1)
            return {"armed": True, "accept": True, "verdict": "accept", "reason": "spy"}

        monkeypatch.setattr(gate_mod, "gate_verdict", _spy)

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)

        assert result["ok"] is False
        assert result["error"] == "hypothesis_missing"
        assert calls == [], "a recordless round must never be scored"

    def test_val_reference_in_the_check_is_refused(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_pack(git_ws)
        payload = _good_hypothesis()
        payload["mechanism_check"] = [
            {"id": "pair-1", "before": "ran the val task", "after": "changed"}  # a val id
        ]
        hypothesis_mod.record_hypothesis(payload)

        monkeypatch.setattr(
            gate_mod,
            "gate_verdict",
            lambda: {"armed": True, "accept": True, "verdict": "accept"},
        )

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)

        assert result["error"] == "hypothesis_missing"
        assert "pair-1" in json.dumps(result, ensure_ascii=False)

    def test_valid_hypothesis_reaches_the_gate(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_pack(git_ws)
        # The Parent bar comes from the separate, mutation-free measurement —
        # a candidate must never write its own result into the bar.
        half = {"pair-1": "aurora", "pair-2": "wrong"}
        _solve(1, half)
        _solve(2, half)
        parent = gate_mod.establish_parent_baseline()
        assert parent["ok"] is True and parent["score"] == 0.5, parent

        # A candidate that stated its claim reaches the gate and clears it.
        hypothesis_mod.record_hypothesis(_good_hypothesis())
        _solve(1, {"pair-1": "aurora", "pair-2": "aurora"})
        _solve(2, {"pair-1": "aurora", "pair-2": "aurora"})

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        assert result["bench_pack"]["verdict"] == "accept"

    def test_hypothesis_rejection_is_soft_and_retryable(self, git_ws: Path) -> None:
        _freeze_pack(git_ws)
        hypothesis_mod.clear_hypothesis()
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["failure_mode"]["mode"] == "soft"
        assert result["failure_mode"]["reasonClass"] == "hypothesis"
        assert result["next_action"] == "swarm_tick"


# ---------------------------------------------------------------------------
# Pack verdicts reaching solidify
# ---------------------------------------------------------------------------


class TestPackVerdictsAtSolidify:
    def _with_hypothesis(self) -> None:
        hypothesis_mod.record_hypothesis(_good_hypothesis())

    def test_flat_rejects(self, git_ws: Path) -> None:
        """round-79 passed a flat score; it now loses and moves nothing."""
        _freeze_pack(git_ws)
        half = {"pair-1": "aurora", "pair-2": "wrong"}
        _solve(1, half)
        _solve(2, half)
        parent = gate_mod.establish_parent_baseline()
        assert parent["ok"] is True and parent["score"] == 0.5

        # This candidate states its claim and scores the same 0.5 → flat.
        self._with_hypothesis()
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "bench_pack_rejected"
        assert result["details"]["bench_pack"]["reason"] == "flat"
        assert gate_mod.load_baseline()["score"] == 0.5

    def test_unmeasured_rejects(self, git_ws: Path) -> None:
        """An unsolved val split is not evidence of anything."""
        _freeze_pack(git_ws)
        self._with_hypothesis()
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["error"] == "bench_pack_rejected"
        assert result["details"]["bench_pack"]["reason"] == "unmeasured"
        assert gate_mod.load_baseline() is None

    def test_gate_exception_rejects_instead_of_degrading(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken instrument means 'we measured nothing', not 'all clear'."""
        _freeze_pack(git_ws)
        self._with_hypothesis()

        def _boom() -> dict[str, Any]:
            raise OSError("grader exploded")

        monkeypatch.setattr(gate_mod, "gate_verdict", _boom)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "bench_pack_rejected"
        assert result["details"]["bench_pack"]["reason"] == "gate_error"


# ---------------------------------------------------------------------------
# Sealed proposal round
# ---------------------------------------------------------------------------


class TestSealedProposalRound:
    def test_proposal_carrying_val_material_is_refused(self, git_ws: Path, tmp_path: Path) -> None:
        _freeze_pack(git_ws)
        hypothesis_mod.record_hypothesis(_good_hypothesis())

        secrets = val_seal.sealed_secrets()
        strong = next(entry for entry in secrets if entry["signal"] == "strong")
        payload = {
            "action": "no_action",
            "note": f"the val task asks: {strong['value']}",
        }
        proposal_path = tmp_path / "proposal.json"
        proposal_path.write_text(json.dumps(payload), encoding="utf-8")

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True, proposal=proposal_path)

        assert result["ok"] is False
        assert result["error"] == "val_seal_breach"
        assert result["details"]["val_seal"]["where"] == "proposal_round"

    def test_clean_proposal_is_not_refused_for_sealing(self, git_ws: Path, tmp_path: Path) -> None:
        """Guarding the seal must not turn into a blanket refusal."""
        _freeze_pack(git_ws)
        hypothesis_mod.record_hypothesis(_good_hypothesis())

        payload = {"action": "no_action", "note": "nothing today"}
        proposal_path = tmp_path / "clean.json"
        proposal_path.write_text(json.dumps(payload), encoding="utf-8")

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True, proposal=proposal_path)

        assert result.get("error") != "val_seal_breach"
        assert result.get("action") == "no_action"


# ---------------------------------------------------------------------------
# Session ledger fold (round-86 seams)
# ---------------------------------------------------------------------------


class TestSessionLedgerFold:
    """solidify judged the Candidate but never opened the round.

    round-86 seams, both fixed here: the fold opens the round (budget moves,
    the candidate is named), and the hypothesis check accepts the session's
    own round scope beside the swarm cycle id.
    """

    def _open_session(self) -> dict[str, Any]:
        from evolver.gep.evolution_session import EvolutionSession

        return EvolutionSession().start_run("parent-gene")

    def test_a_refusal_opens_the_round_and_burns_budget(self, git_ws: Path) -> None:
        from evolver.gep.evolution_session import EvolutionSession

        self._open_session()
        _freeze_pack(git_ws)
        hypothesis_mod.record_hypothesis(_good_hypothesis())
        write_state_for_solidify(_last_run())

        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "bench_pack_rejected"

        session = EvolutionSession()
        run = session.latest_run()
        assert run["status"] == "running"
        assert run["round"] == 1, "one measured refusal is one round of budget"
        assert run["current_candidate"] == "mut_paired_gate"

        entry = json.loads(
            (session.run_dir / "rounds.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        assert entry["candidate"] == "mut_paired_gate"
        assert entry["cycle_ref"] == "run_paired_gate"
        assert entry["decision"] == "reject"

    def test_a_retried_cycle_does_not_burn_a_second_round(self, git_ws: Path) -> None:
        """One Candidate, one round — however many times solidify retries."""
        from evolver.gep.evolution_session import EvolutionSession

        self._open_session()
        _freeze_pack(git_ws)
        hypothesis_mod.record_hypothesis(_good_hypothesis())
        write_state_for_solidify(_last_run())
        assert solidify(skip_validation=True)["ok"] is False

        # Same pending cycle again (same run_id): the idempotence key must
        # keep the ledger honest instead of spending the budget twice.
        write_state_for_solidify(_last_run())
        assert solidify(skip_validation=True)["ok"] is False

        session = EvolutionSession()
        assert session.latest_run()["round"] == 1
        assert session.rejected_count() == 1

    def test_a_published_gate_lets_session_accept_land(self, git_ws: Path) -> None:
        """round-86 seam: after an ``accept: true`` gate record, ``session
        accept`` used to fail with "No Candidate" because no round had ever
        been opened. The fold opens it; the Accept closes the deal."""
        from evolver.gep.evolution_session import EvolutionSession

        self._open_session()
        _freeze_pack(git_ws)
        half = {"pair-1": "aurora", "pair-2": "wrong"}
        _solve(1, half)
        _solve(2, half)
        parent = gate_mod.establish_parent_baseline()
        assert parent["ok"] is True and parent["score"] == 0.5

        hypothesis_mod.record_hypothesis(_good_hypothesis())
        _solve(1, {"pair-1": "aurora", "pair-2": "aurora"})
        _solve(2, {"pair-1": "aurora", "pair-2": "aurora"})

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True

        ev = EvolutionSession()
        ev.resume()
        ref = ev.accept()
        assert ref
        assert ev.latest_run()["status"] == "accepted"

    def test_session_scoped_hypothesis_counts_as_this_round(self, git_ws: Path) -> None:
        """round-86 seam: ``session hypothesize`` stamps the session's own
        round scope (``run_1``), while solidify checked the swarm cycle id —
        two id systems, so every CLI-declared hypothesis was refused."""
        opened = self._open_session()
        _freeze_pack(git_ws)
        payload = _good_hypothesis()
        payload["run_id"] = str(opened["run_id"])  # session scope, not the cycle id
        hypothesis_mod.record_hypothesis(payload)

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        # It reaches the pack gate (unmeasured → reject), NOT the hypothesis gate.
        assert result["error"] == "bench_pack_rejected"
        assert result["details"]["bench_pack"]["reason"] == "unmeasured"

    def test_a_leftover_record_from_another_round_is_still_refused(self, git_ws: Path) -> None:
        """The widening accepts the session scope — it does not open the door."""
        self._open_session()
        _freeze_pack(git_ws)
        payload = _good_hypothesis()
        payload["run_id"] = "run_from_a_previous_cycle"
        hypothesis_mod.record_hypothesis(payload)

        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["error"] == "hypothesis_missing"
        # The refusal names the mismatch (human wording, not the reason code).
        assert "another round" in json.dumps(result, ensure_ascii=False)
