"""Soak environment helper (演进方案.md §10) — keep runtime off the git tree."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evolver.ops.soak_env import (
    evolution_dir_inside_repo,
    exports_shell,
    gate_verifications_path,
    path_is_inside,
    read_gate_verifications,
    setup,
    soak_root,
    status,
)


def test_path_is_inside(tmp_path: Path) -> None:
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert path_is_inside(inner, tmp_path) is True
    assert path_is_inside(tmp_path, inner) is False


def test_setup_is_idempotent(temp_workspace: Path) -> None:
    lessons = temp_workspace / "memory" / "evolution" / "LESSONS_LEARNED.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text("# lessons\n", encoding="utf-8")

    first = setup()
    assert first["ok"] is True
    assert Path(first["evolution_dir"]).is_dir()
    assert Path(first["gep_assets_dir"]).is_dir()
    assert Path(first["env_sh"]).is_file()
    assert first["copied_lessons"] is True
    assert (Path(first["evolution_dir"]) / "LESSONS_LEARNED.md").is_file()

    second = setup()
    assert second["copied_lessons"] is False
    assert soak_root() == Path(first["root"])


def test_exports_point_at_soak_root(temp_workspace: Path) -> None:
    text = exports_shell()
    root = soak_root()
    assert f'EVOLUTION_DIR="{root / "evolution"}"' in text
    assert f'GEP_ASSETS_DIR="{root / "gep"}"' in text


def test_status_flags_in_repo_layout(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # temp_workspace sets EVOLUTION_DIR under the sandbox, not the product repo.
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("EVOLUTION_DIR", str(temp_workspace / "memory" / "evolution"))
    assert evolution_dir_inside_repo() is True
    report = status()
    assert report["inside_repo"] is True
    assert report["metrics"]["gated_runs"] >= 0


class TestGateVerificationLedger:
    """Round-30 (演进方案.md §11.4 P0-1): the human adjudication ledger lives
    outside every workspace (anchor dir) and is read-only for the engine. A
    malformed row is skipped, never fatal — this is advisory human evidence."""

    def _write(self, text: str) -> None:
        path = gate_verifications_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_missing_ledger_is_empty(self, temp_workspace: Path) -> None:
        assert read_gate_verifications() == {}

    def test_reads_verdicts(self, temp_workspace: Path) -> None:
        self._write(
            '{"event_id": "evt_a", "verdict": "true_positive", "by": "human"}\n'
            '{"event_id": "evt_b", "verdict": "false_kill", "by": "human"}\n'
        )
        assert read_gate_verifications() == {
            "evt_a": "true_positive",
            "evt_b": "false_kill",
        }

    def test_malformed_rows_skipped(self, temp_workspace: Path) -> None:
        self._write(
            "not json\n"
            '{"verdict": "true_positive"}\n'  # no event_id
            '{"event_id": "evt_c"}\n'  # no verdict
            "[1,2,3]\n"  # not an object
            '{"event_id": "evt_d", "verdict": "true_positive"}\n'
        )
        assert read_gate_verifications() == {"evt_d": "true_positive"}

    def test_status_carries_verified_counts(self, temp_workspace: Path) -> None:
        report = status()
        assert report["metrics"]["verified_true_positives"] == 0
        criteria = report["recommendation"]["criteria"]
        assert criteria["min_verified_true_positives"] == 1


def test_cli_soak_setup_and_exports(
    temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.cli import main

    assert main(["soak", "setup"]) == 0
    out = capsys.readouterr().out
    assert "env.sh" in out
    assert main(["soak", "exports"]) == 0
    exports = capsys.readouterr().out
    assert "export EVOLUTION_DIR=" in exports
    assert main(["soak", "status", "--json"]) == 0


class TestSoakInterlock:
    """S11.4 / P1 #4: Out-of-tree soak interlock tests."""

    def test_is_test_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.ops.soak_env import is_test_environment

        assert is_test_environment() is True

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("EVOLVER_TEST_MODE", raising=False)
        monkeypatch.delenv("EVOLVER_NO_PARENT_GIT", raising=False)
        assert is_test_environment() is False

        monkeypatch.setenv("EVOLVER_TEST_MODE", "1")
        assert is_test_environment() is True

        monkeypatch.delenv("EVOLVER_TEST_MODE", raising=False)
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
        assert is_test_environment() is True

    def test_maybe_route_bypassed_in_test_env(self) -> None:
        from evolver.ops.soak_env import maybe_route_to_soak

        res = maybe_route_to_soak()
        assert res["routed"] is False
        assert res["reason"] == "test_environment"

    def test_maybe_route_bypassed_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.ops.soak_env import maybe_route_to_soak

        monkeypatch.setenv("EVOLVER_SOAK_ALLOW_INSIDE", "1")
        res = maybe_route_to_soak()
        assert res["routed"] is False
        assert res["reason"] == "bypassed_by_env"

    def test_maybe_route_already_outside(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.ops.soak_env import maybe_route_to_soak

        # Outside repo: repo root is None
        monkeypatch.delenv("EVOLVER_REPO_ROOT", raising=False)
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
        # Ensure inside_repo is False
        res = maybe_route_to_soak(force=False)
        assert res["routed"] is False

    def test_maybe_route_force_routes_and_seeds(
        self,
        temp_workspace: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from evolver.ops.soak_env import evolution_dir_inside_repo, maybe_route_to_soak, soak_root

        # Point EVOLVER_HOME outside ws (like ~/.evomap is outside the repo in production)
        out_home = tmp_path / "user_home" / ".evomap"
        monkeypatch.setenv("EVOLVER_HOME", str(out_home))

        # Seed in-repo assets
        ws = temp_workspace
        gep_dir = ws / ".evolver" / "gep"
        gep_dir.mkdir(parents=True, exist_ok=True)
        (gep_dir / "events.jsonl").write_text('{"event": 1}\n', encoding="utf-8")
        (gep_dir / "genes.json").write_text('[{"id": "g1"}]\n', encoding="utf-8")

        evo_dir = ws / "memory" / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)
        (evo_dir / "LESSONS_LEARNED.md").write_text("# lessons\n", encoding="utf-8")
        (evo_dir / "feedback.jsonl").write_text('{"fb": 1}\n', encoding="utf-8")

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(ws))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(gep_dir))

        assert evolution_dir_inside_repo() is True

        res = maybe_route_to_soak(force=True, copy_existing=True)
        assert res["routed"] is True
        assert res["soak_root"] == str(soak_root())

        # Check environment variables were updated
        assert os.environ["EVOLUTION_DIR"] == str(soak_root() / "evolution")
        assert os.environ["GEP_ASSETS_DIR"] == str(soak_root() / "gep")

        # Now evolution_dir_inside_repo is False (outside repo)
        assert evolution_dir_inside_repo() is False

        # Seeded assets were copied
        assert (soak_root() / "gep" / "events.jsonl").is_file()
        assert (soak_root() / "gep" / "genes.json").is_file()
        assert (soak_root() / "evolution" / "LESSONS_LEARNED.md").is_file()
        assert (soak_root() / "evolution" / "feedback.jsonl").is_file()

        # Check stderr notice
        err = capsys.readouterr().err
        assert "[soak] Notice: in-repo runtime detected" in err

    def test_cli_charter_check_with_soak(
        self,
        temp_workspace: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from evolver.cli import main

        out_home = tmp_path / "user_home" / ".evomap"
        monkeypatch.setenv("EVOLVER_HOME", str(out_home))
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))

        code = main(["charter-check", "--soak"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Charter Machine Receipt" in captured.out
        # With --soak, inside_repo is False and outside_met is True
        assert "inside_repo=False (outside_met=True)" in captured.out
