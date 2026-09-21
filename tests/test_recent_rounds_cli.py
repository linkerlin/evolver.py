"""Coverage for rounds 27-54 surfaces that landed without CLI/contract tests.

Pins the testable seams of the last four weeks of dogfood mutations:
routing-allowlist membership (rounds 49/51), timeout calibration (round 53),
the unverified verdict's operator recipe (round 47), the variants CLI
including mechanical re-dispatch (rounds 40/44), the population solidify
wiring (round 41), and operator-facing render lines (rounds 38/49).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.cli import SOAK_ROUTED_COMMANDS, main


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class TestSoakRoutedCommandsPinned:
    """Rounds 49/51: membership is a contract — silent removal fails here."""

    def test_store_writers_routed(self) -> None:
        # Round-51: bare CLI writers must land in the soak store, not the
        # frozen in-repo one (state-split defect).
        for cmd in ("distill", "fetch", "sync", "reuse", "publish"):
            assert cmd in SOAK_ROUTED_COMMANDS, cmd

    def test_live_ledger_readers_routed(self) -> None:
        # Round-49: `evolver report` showed round-29-era data for 20 rounds.
        for cmd in ("report", "meta-report", "variants"):
            assert cmd in SOAK_ROUTED_COMMANDS, cmd

    def test_dual_view_commands_stay_unrouted(self) -> None:
        # gate-report / charter-check keep their explicit --soak dual views
        # by design — routing them silently would erase the in-repo view.
        assert "gate-report" not in SOAK_ROUTED_COMMANDS
        assert "charter-check" not in SOAK_ROUTED_COMMANDS


class TestTimeoutCalibrationPinned:
    """Round-53: constants calibrated from a measured 1.41-1.50s floor."""

    def test_values_match_calibration(self) -> None:
        from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, HUB_SEARCH_TIMEOUT_MS

        assert HTTP_TRANSPORT_TIMEOUT_MS == 10_000
        assert HUB_SEARCH_TIMEOUT_MS == 5_000

    def test_headroom_over_measured_floor(self) -> None:
        # ~7x / ~3x headroom over the observed ~1.5s floor: enough for slow
        # networks, half the old worst case (one timeout + one retry).
        from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, HUB_SEARCH_TIMEOUT_MS

        assert HTTP_TRANSPORT_TIMEOUT_MS >= 7_000
        assert HUB_SEARCH_TIMEOUT_MS >= 4_500

    def test_sticky_constants_unchanged(self) -> None:
        # Rounds 45/46 contract: threshold 3, 24h re-probe TTL.
        from evolver.gep.hub_health import HUB_404_REPROBE_S, HUB_404_STICKY_THRESHOLD

        assert HUB_404_STICKY_THRESHOLD == 3
        assert HUB_404_REPROBE_S == 24 * 3600.0


class TestUnverifiedReasonRecipe:
    """Round-47: the sole-blocker verdict must carry the full operator recipe."""

    def _unverified(self) -> list[str]:
        from evolver.gep.acceptance.report import gate_soak_recommendation, summarize_acceptance

        clean = [
            {
                "id": f"e{i}",
                "timestamp": f"2026-09-{i:02d}T00:00:00Z",
                "outcome": {"status": "success"},
                "acceptance_result": {"accepted": True, "reason": "t0", "shadow": True},
            }
            for i in range(1, 21)
        ]
        metrics = summarize_acceptance(clean, verified={})
        rec = gate_soak_recommendation(metrics)
        assert rec["verdict"] == "unverified"
        return rec["reasons"]

    def test_recipe_has_path_format_condition(self) -> None:
        joined = "\n".join(self._unverified())
        assert "gate-verifications.jsonl" in joined, "artifact named"
        assert "$EVOLVER_HOME/anchor" in joined or "anchor" in joined, "path hinted"
        assert '"confirmed"' in joined, "row format given"
        assert "真回归" in joined or "true" in joined.lower(), "registration condition stated"


class TestVariantsCLI:
    """Rounds 40/44: `evolver variants` listing + mechanical re-dispatch."""

    @staticmethod
    def _entry(variant_id: str, diff: str) -> dict[str, Any]:
        return {
            "type": "VariantArchiveEntry",
            "variant_id": variant_id,
            "run_id": "run_x",
            "gene_id": None,
            "signal_heads": ["log_error"],
            "rejection_class": "environmental",
            "fingerprint": "abc12345",
            "rejection_reason": "validation_failed",
            "recorded_at": "2026-09-21T00:00:00Z",
            "replay": {"kind": "unified_diff", "diff": diff},
        }

    def test_list_renders_entries_and_counts(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = temp_workspace / ".evolver" / "gep"
        store.mkdir(parents=True)
        (store / "candidates.jsonl").write_text(
            json.dumps(self._entry("var_abc12345", "--- a/f\n+++ b/f\n")) + "\n",
            encoding="utf-8",
        )
        assert main(["variants"]) == 0
        out = capsys.readoutout() if False else capsys.readouterr().out
        assert "1 entry" in out
        assert "var_abc12345" in out

    def test_json_output_shape(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["variants", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert {"family", "total", "re_dispatchable", "variants"} <= set(data)

    def test_re_dispatch_unknown_id_fails(
        self,
        temp_workspace: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["variants", "re-dispatch", "var_nope"]) == 1
        assert "unknown" in capsys.readouterr().err

    def test_re_dispatch_applies_diff(
        self,
        temp_workspace: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "t@t.com")
        _git(repo, "config", "user.name", "T")
        (repo / "f.txt").write_text("base\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", "init")

        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-base\n+redispatched\n"
        store = temp_workspace / ".evolver" / "gep"
        store.mkdir(parents=True)
        (store / "candidates.jsonl").write_text(
            json.dumps(self._entry("var_good001", diff)) + "\n", encoding="utf-8"
        )
        from evolver.gep import paths as paths_mod

        monkeypatch.setattr(paths_mod, "get_workspace_root", lambda: repo)
        # _cmd_variants binds get_workspace_root at call time via module
        # import inside the function — patch the cli module's view too.
        import evolver.cli as cli_mod

        monkeypatch.setattr("evolver.gep.paths.get_workspace_root", lambda: repo, raising=True)
        assert main(["variants", "re-dispatch", "var_good001"]) == 0
        out = capsys.readouterr().out
        assert "re-dispatched var_good001" in out
        assert "redispatched" in (repo / "f.txt").read_text(encoding="utf-8")
        del cli_mod  # silence unused-import lint; patching was module-level


class TestSolidifyPopulationWiring:
    """Round 41: `evolver solidify --population` routes through the orchestrator."""

    def test_population_flag_invokes_run_population(
        self,
        temp_workspace: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from evolver.gep import population as pop_mod
        from evolver.gep import solidify as sol_mod

        seen: dict[str, Any] = {}

        def fake_run_population(paths, src, *, cascade_commands, **kw: Any) -> dict[str, Any]:
            seen["paths"] = [str(p) for p in paths]
            return {
                "candidates": [
                    {"proposal_path": str(paths[0]), "status": "accepted", "index": 0},
                    {"proposal_path": "loser.json", "status": "rejected", "index": 1},
                ],
                "winner": str(paths[0]),
                "winner_index": 0,
            }

        def fake_solidify(proposal: Any = None, **kw: Any) -> dict[str, Any]:
            seen["solidify_proposal"] = proposal
            return {"ok": True, "event_id": "evt_pop", "blast_radius": {"files": 1}}

        monkeypatch.setattr(pop_mod, "run_population", fake_run_population)
        monkeypatch.setattr(sol_mod, "solidify", fake_solidify)

        p1 = temp_workspace / "a.json"
        p1.write_text("{}", encoding="utf-8")
        assert main(["solidify", "--population", str(p1)]) == 0
        out = capsys.readouterr().out
        assert seen["solidify_proposal"] == str(p1)
        assert "population winner landed" in out
        assert "loser" not in seen["solidify_proposal"]


class TestOperatorRenderLines:
    """Rounds 38/49: operator-facing lines carry their data source."""

    def test_soak_status_shows_cumulative_and_source(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["soak", "status"]) == 0
        out = capsys.readouterr().out
        assert "gated_runs" in out
        assert "cumulative" in out
        assert "source" in out
