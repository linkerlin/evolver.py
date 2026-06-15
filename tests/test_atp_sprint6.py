"""Tests for Sprint 6 ATP deepening — CLI, execute, task pickup, mailbox transport."""

from __future__ import annotations

import argparse as ap
import asyncio
import json
from pathlib import Path

import pytest

from evolver.atp import atp_execute, cli
from evolver.atp.atp_task_pickup import (
    _compute_capability_match,
    _compute_roi,
    _estimate_effort,
    _score_task,
    forget,
)
from evolver.gep import mailbox_transport

# ---------------------------------------------------------------------------
# CLI subcommand registration
# ---------------------------------------------------------------------------


class TestCliSubcommands:
    def test_all_commands_in_map(self) -> None:
        expected = {
            "status", "enable", "disable", "buy", "orders",
            "tasks", "claim", "deliver", "settle", "dispute",
            "publish", "policy", "proofs", "tier", "order",
        }
        assert expected == set(cli._COMMAND_MAP.keys())

    def test_buy_requires_service_id(self) -> None:
        parser = ap.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cli.add_atp_subparsers(sub)
        args = parser.parse_args(["atp", "buy", "my-service", "--budget", "10"])
        assert args.service_id == "my-service"
        assert args.budget == 10.0

    def test_unknown_command_returns_error(self) -> None:
        args = type("Args", (), {"atp_command": "nonexistent"})()
        result = asyncio.run(cli.run_atp_command(args))
        assert result == 1


def _cmd_args(cmd: str) -> list[str]:
    extras: dict[str, list[str]] = {
        "buy": ["svc-1"],
        "claim": ["task-1"],
        "deliver": ["order-1"],
        "settle": ["order-1"],
        "dispute": ["order-1", "--reason", "bad"],
        "publish": ["spec.json"],
        "tier": [],
        "order": ["order-1"],
        "proofs": [],
    }
    return extras.get(cmd, [])


# ---------------------------------------------------------------------------
# ATP execute — proof building + validation
# ---------------------------------------------------------------------------


class TestAtpExecute:
    def test_build_gene(self) -> None:
        task = {"task_id": "t1", "atp_order_id": "o1"}
        gene = atp_execute._build_gene(task)
        assert gene["id"] == "atp-t1"
        assert gene["asset_id"].startswith("sha256:")

    def test_build_capsule(self) -> None:
        task = {"task_id": "t1", "atp_order_id": "o1"}
        capsule = atp_execute._build_capsule("answer text", task)
        assert capsule["content"] == "answer text"
        assert capsule["a2a"]["atp"]["order_id"] == "o1"

    def test_build_proof_includes_hash(self) -> None:
        task = {"task_id": "t1", "atp_order_id": "o1"}
        gene = atp_execute._build_gene(task)
        capsule = atp_execute._build_capsule("answer", task)
        proof_str = atp_execute._build_proof("answer", task, gene, capsule)
        proof = json.loads(proof_str)
        assert proof["answer_hash"].startswith("sha256:")
        assert proof["task_id"] == "t1"

    def test_run_validation_rejects_shell_operators(self) -> None:
        result = atp_execute._run_validation(["python -c 'print(1)'; rm -rf /"])
        assert not result["passed"]

    def test_run_validation_allows_python(self) -> None:
        result = atp_execute._run_validation(["python --version"])
        assert result["passed"]

    def test_complete_missing_file(self) -> None:
        result = asyncio.run(atp_execute.complete_atp_task("t1", "/nonexistent"))
        assert not result["ok"]
        assert result["error"] == "answer_file_not_found"


# ---------------------------------------------------------------------------
# Task pickup — ROI scoring + capability matching
# ---------------------------------------------------------------------------


class TestTaskPickup:
    def test_estimate_effort_simple(self) -> None:
        effort = _estimate_effort({"question": "short"})
        assert 1.0 <= effort <= 10.0

    def test_compute_roi(self) -> None:
        task = {"bounty": 10.0, "question": "easy task"}
        roi = _compute_roi(task)
        assert roi > 0

    def test_capability_match_no_requirements(self) -> None:
        score = _compute_capability_match({})
        assert score == 1.0

    def test_capability_match_with_pool(self) -> None:
        task = {"capabilities": ["repair"], "signals": []}
        pool = [{"signals_match": ["repair", "error"]}]
        score = _compute_capability_match(task, pool)
        assert score > 0

    def test_score_task_eligible(self) -> None:
        task = {"bounty": 5.0, "question": "do something", "capabilities": []}
        score = _score_task(task)
        assert "roi" in score
        assert "capability_match" in score
        assert "eligible" in score

    def test_forget_clears_ledger(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
        import evolver.gep.paths as paths_mod  # noqa: PLC0415

        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path / "memory")
        forget("test-task-id")
        # Should not raise.


# ---------------------------------------------------------------------------
# Mailbox transport — URL building + proxy check
# ---------------------------------------------------------------------------


class TestMailboxTransport:
    def test_proxy_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_PROXY_PORT", "9999")
        url = mailbox_transport._proxy_base_url()
        assert "9999" in url
        assert "/v1/a2a" in url

    def test_is_proxy_running_returns_false_for_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_PROXY_PORT", "1")  # port 1 is never open
        assert mailbox_transport._is_proxy_running() is False
