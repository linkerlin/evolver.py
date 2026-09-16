"""Tests for evolver.gep.anchor + the solidify anchor hook (RSI P0-1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import anchor as anchor_mod
from evolver.gep import solidify as solidify_mod
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def anchor_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated workspace AND isolated anchor home."""
    monkeypatch.setenv("EVOLVER_HOME", str(temp_workspace / ".evomap"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.delenv("EVOLVER_NO_PARENT_GIT", raising=False)
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "t@t.com")
    _git(temp_workspace, "config", "user.name", "T")
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    _git(temp_workspace, "add", "-A")
    _git(temp_workspace, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return temp_workspace


def _install_seed(anchor_ws: Path) -> dict[str, Any]:
    result = anchor_mod.install_anchor_suite()
    assert result["ok"], result
    return result


class TestTriggerDetection:
    def test_verifier_surfaces_match(self) -> None:
        matched = anchor_mod.touches_verifier_surface(
            ["src/evolver/gep/solidify.py", "src/evolver/gep/acceptance/gate.py"]
        )
        assert matched == [
            "src/evolver/gep/solidify.py",
            "src/evolver/gep/acceptance/gate.py",
        ]

    def test_ordinary_files_do_not_match(self) -> None:
        assert anchor_mod.touches_verifier_surface(["src/evolver/webui/app.py", "README.md"]) == []

    def test_anchor_runner_itself_is_guarded(self) -> None:
        from evolver.config import ANCHOR_TRIGGER_SURFACES

        assert "src/evolver/gep/anchor.py" in ANCHOR_TRIGGER_SURFACES


class TestRunner:
    def test_missing_suite_skips_ok(self, anchor_ws: Path) -> None:
        result = anchor_mod.run_anchor_suite()
        assert result["ok"] is True
        assert result["skipped"] == "anchor_suite_not_installed"

    def test_seed_suite_passes_on_clean_tree(self, anchor_ws: Path) -> None:
        _install_seed(anchor_ws)
        result = anchor_mod.run_anchor_suite()
        assert result["ok"] is True, json.dumps(result["results"], ensure_ascii=False)[:800]
        assert len(result["results"]) == len(anchor_mod.list_anchor_cases())
        assert all(c["ok"] for c in result["results"])

    def test_failing_probe_fails_suite(self, anchor_ws: Path) -> None:
        _install_seed(anchor_ws)
        bad = anchor_mod.anchor_dir() / "case-bad-probe"
        bad.mkdir()
        (bad / "case.json").write_text(
            json.dumps({"id": "bad-probe", "title": "always fails"}), encoding="utf-8"
        )
        (bad / "probe.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        result = anchor_mod.run_anchor_suite()
        assert result["ok"] is False
        failed = [c for c in result["results"] if c["id"] == "bad-probe"]
        assert failed and failed[0]["exit_code"] == 3

    def test_epoch_replacement_requires_newer_epoch(self, anchor_ws: Path) -> None:
        first = _install_seed(anchor_ws)
        assert first["epoch"] == 1
        again = anchor_mod.install_anchor_suite(epoch=1)
        assert again["ok"] is False
        assert again["error"] == "epoch_not_newer"
        newer = anchor_mod.install_anchor_suite(epoch=2)
        assert newer["ok"] is True
        assert anchor_mod.load_epoch()["epoch"] == 2


class TestSolidifyHook:
    def _write_run(self, run_id: str = "run_anchor_hook") -> None:
        write_state_for_solidify(
            {
                "run_id": run_id,
                "signals": ["log_error"],
                "selected_gene_id": "g_hook",
                "mutation": {"id": "m_hook", "validation": []},
            }
        )

    def test_verifier_mutation_rejected_on_anchor_failure(
        self, anchor_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_seed(anchor_ws)
        # A mutation touching a verifier surface (this file edit mimics one).
        target = anchor_ws / "src" / "evolver" / "gep" / "solidify.py"
        target.parent.mkdir(parents=True)
        target.write_text("# mutated\n", encoding="utf-8")

        def fake_suite() -> dict[str, Any]:
            return {
                "ok": False,
                "epoch": 1,
                "results": [{"id": "x", "ok": False, "stderr": "boom"}],
            }

        monkeypatch.setattr(solidify_mod, "run_anchor_suite", fake_suite)
        self._write_run()
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "anchor_failed"
        assert result["failure_mode"]["retryable"] is False
        assert result["details"]["touched"] == ["src/evolver/gep/solidify.py"]

    def test_passing_anchor_records_on_event(
        self, anchor_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.paths import get_gep_assets_dir

        _install_seed(anchor_ws)
        target = anchor_ws / "src" / "evolver" / "gep" / "solidify.py"
        target.parent.mkdir(parents=True)
        target.write_text("# mutated\n", encoding="utf-8")

        def fake_suite() -> dict[str, Any]:
            return {
                "ok": True,
                "epoch": 1,
                "results": [{"id": "x", "ok": True}],
            }

        monkeypatch.setattr(solidify_mod, "run_anchor_suite", fake_suite)
        self._write_run()
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        events_path = get_gep_assets_dir() / "events.jsonl"
        evt = json.loads(events_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert evt["anchor_result"]["ok"] is True
        assert evt["anchor_result"]["cases"] == [{"id": "x", "ok": True}]

    def test_ordinary_mutation_skips_anchor(
        self, anchor_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def spy_suite() -> dict[str, Any]:
            called["n"] += 1
            return {"ok": True, "results": []}

        monkeypatch.setattr(solidify_mod, "run_anchor_suite", spy_suite)
        (anchor_ws / "docs" / "note.md").parent.mkdir(exist_ok=True)
        (anchor_ws / "docs" / "note.md").write_text("x\n", encoding="utf-8")
        self._write_run()
        assert solidify(skip_validation=True)["ok"] is True
        assert called["n"] == 0


class TestMetaReport:
    def test_panel_and_audit_rows(self) -> None:
        from evolver.ops.meta_report import build_meta_report

        events = [
            {
                "id": "e1",
                "timestamp": "2026-09-01T00:00:00Z",
                "outcome": {"status": "success", "score": 1.0},
                "mutation": {"landed_gene_ids": ["gene_selector_fix"]},
                "signals": ["preflight_abort", "log_error"],
                "diff_snapshot": "diff --git a/src/evolver/gep/selector.py b/s\n",
            },
            {
                "id": "e2",
                "timestamp": "2026-09-02T00:00:00Z",
                "outcome": {"status": "failed"},
                "signals": ["hub_offline"],
                "diff_snapshot": "diff --git a/src/evolver/webui/app.py b/s\n",
            },
            {
                "id": "e3",
                "timestamp": "2026-09-03T00:00:00Z",
                "outcome": {"status": "success"},
                "mutation": {"landed_gene_ids": ["gene_selector_fix"]},
                "signals": ["hub_offline"],
                "diff_snapshot": "diff --git a/README.md b/s\n",
            },
        ]
        report = build_meta_report(events, [])
        panel = report["panel"]
        assert panel["adaptivity"]["accepted"] == 2
        assert panel["adaptivity"]["failed"] == 1
        assert panel["meta_recursion"]["structural_l5_mutations"] == 1
        audit = report["mechanism_audit"]
        assert audit[0]["mechanism_files"] == ["src/evolver/gep/selector.py"]
        assert audit[0]["descendant_success_rate"] == 0.5
        # gene_selector_fix landed under two signal families → transfer
        assert panel["transfer"]["genes_under_multiple_signal_families"] == 1

    def test_descendant_recurrence_detection(self) -> None:
        from evolver.ops.meta_report import build_meta_report

        events = [
            {
                "id": "e1",
                "outcome": {"status": "success"},
                "mutation": {"landed_gene_ids": ["gene_x"]},
                "signals": ["log_error"],
            },
            {
                "id": "e2",
                "outcome": {"status": "failed"},
                "signals": ["log_error", "hub_offline"],
            },
        ]
        report = build_meta_report(events, [])
        dq = report["descendant_quality"]
        assert dq and dq[0]["resolved"] is False
        assert dq[0]["signal_recurrence_in_failures"] == 1
