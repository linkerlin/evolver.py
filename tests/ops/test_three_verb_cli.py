"""P0-2 (支柱零): three-verb CLI surface — init / up (auto) / status.

Machine criteria: the root help leads with the three verbs and folds the
60+ expert commands behind ``evolver internal`` (old top-level spellings
still work); ``evolver status`` speaks plain language with zero internal
flags; ``up`` ships the adaptive sliding session and the 3-round dormancy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.cli import main
from evolver.ops.autopilot import Dormancy, SessionSlider


class TestRootHelp:
    def test_root_help_leads_with_three_verbs(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for verb in ("init", "up", "status", "internal"):
            assert verb in out, out
        assert "auto" in out  # up's alias is named on the help screen

    def test_root_help_hides_expert_dump(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        # Expert commands stay out of the primary screen…
        assert "gate-report" not in out
        assert "establish-parent" not in out
        # …and remain discoverable behind the internal shim.
        assert "internal <cmd>" in out

    def test_internal_help_lists_experts(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        assert main(["internal"]) == 0
        out = capsys.readouterr().out
        assert "gate-report" in out  # the full expert listing is one hop away

    def test_internal_dash_help_works_without_error(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        assert main(["internal", "--help"]) == 0
        out = capsys.readouterr().out
        assert "gate-report" in out

        assert main(["internal", "-h"]) == 0
        out_short = capsys.readouterr().out
        assert "gate-report" in out_short

        with pytest.raises(SystemExit) as exc:
            main(["internal", "doctor", "--help"])
        assert exc.value.code == 0
        doc_out = capsys.readouterr().out
        assert "--fix" in doc_out

    def test_ensure_utf8_stdio_reconfigures_cp936_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        from evolver.cli import _ensure_utf8_stdio

        class _FakeStream:
            def __init__(self, enc: str) -> None:
                self.encoding = enc
                self.errors = "strict"
                self.calls: list[tuple[str | None, str | None]] = []

            def reconfigure(
                self, *, encoding: str | None = None, errors: str | None = None
            ) -> None:
                self.calls.append((encoding, errors))
                if encoding:
                    self.encoding = encoding
                if errors:
                    self.errors = errors

        fake_out = _FakeStream("cp936")
        fake_err = _FakeStream("gbk")
        monkeypatch.setattr(sys, "stdout", fake_out)
        monkeypatch.setattr(sys, "stderr", fake_err)

        _ensure_utf8_stdio(force=True)
        assert fake_out.encoding == "utf-8" and fake_out.errors == "replace"
        assert fake_err.encoding == "utf-8" and fake_err.errors == "replace"

    def test_up_once_prints_concise_human_summary_not_prompt_dump(
        self,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=temp_workspace, check=True)
        monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
        rc = main(["up", "--once", "--project", str(temp_workspace)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "单轮巡检完成" in out
        assert "BUILT_PROMPT" not in out
        assert "SOLIDIFY REQUIRED" not in out

    def test_old_top_level_spelling_still_routes(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        assert main(["status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "project" in payload

    def test_typo_command_suggests_closest_verb_without_expert_dump(
        self, temp_workspace: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["statu"])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "evolver status" in err
        assert "establish-parent" not in err

    def test_init_human_output_and_no_hosts_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        import subprocess

        repo = tmp_path / "demo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))
        monkeypatch.setattr(
            "evolver.ops.init_bootstrap._spawn_baseline_child",
            lambda _p: {"ok": True, "pid": None},
        )
        rc = main(["init", "--project", str(repo), "--no-hosts"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "一键开箱就绪" in out
        assert "evolver status" in out


class TestHumanStatus:
    def test_panel_is_jargon_free(self, temp_workspace: Path) -> None:
        from evolver.ops.status_human import human_status, render_human

        report = human_status()
        text = render_human(report)
        assert report["ready"]
        for line in text.splitlines():
            for flag in ("soft_gap", "loop_fuse", "gate_soft_continue", "pending_solidify"):
                assert flag not in line, line
        assert "工作台草稿" in text
        assert "金库算子" in text

    def test_status_command_exit_zero(self, temp_workspace: Path) -> None:
        assert main(["status"]) == 0

    def test_status_separates_unverified_soft_accept_from_promoted(
        self, temp_workspace: Path
    ) -> None:
        from evolver.gep.paths import get_workspace_state_dir
        from evolver.ops.status_human import human_status, render_human

        state_dir = get_workspace_state_dir(temp_workspace)
        events_path = state_dir / "gep" / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": "evt_soft",
                            "run_id": "run_soft",
                            "outcome": {"status": "success"},
                            "bench_pack": {"verdict": "soft_accept", "soft_accept": True},
                            "validation_report": {"commands": ["ruff check a.py"]},
                        }
                    ),
                    json.dumps(
                        {
                            "id": "evt_real",
                            "run_id": "run_real",
                            "outcome": {"status": "success"},
                            "bench_pack": {"verdict": "soft_accept", "soft_accept": True},
                            "validation_report": {"commands": ["pytest -q tests/test_a.py"]},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        panel = human_status(project=temp_workspace)
        assert panel["promoted"] == 1
        assert panel["soft_accepted"] == 1
        text = render_human(panel)
        assert "未验软放行" in text
        assert "已晋升修复   : 1 轮" in text


class TestDormancy:
    def test_dormant_after_three_idle_rounds(self, temp_workspace: Path) -> None:
        d = Dormancy(repo=temp_workspace)
        assert not d.dormant
        assert d.observe() is False
        d.observe()
        assert not d.dormant
        d.observe()
        assert d.dormant
        # Dormant sleep stretches but stays bounded.
        assert d.sleep_s(5.0) > 5.0
        assert d.sleep_s(5.0) <= 300.0

    def test_progress_resets_the_streak(self, temp_workspace: Path) -> None:
        d = Dormancy(repo=temp_workspace)
        d.observe()
        d.observe()
        assert d.no_progress == 2
        # Raw event churn (a FAILURE round also appends events) is not
        # progress — round-121 review. Only a success-settled round wakes it.
        from evolver.ops.autopilot import _events_path

        events = _events_path()
        events.parent.mkdir(parents=True, exist_ok=True)
        events.write_text('{"outcome": {"status": "failed"}}\n', encoding="utf-8")
        assert d.observe() is False
        d.observe()
        assert d.no_progress == 4
        events.write_text('{"outcome": {"status": "success"}}\n', encoding="utf-8")
        assert d.observe() is True
        assert d.no_progress == 0

    def test_dormant_wait_wakes_early_on_new_commit(self, temp_workspace: Path) -> None:
        import asyncio
        import subprocess

        subprocess.run(
            ["git", "init"], cwd=temp_workspace, check=True, capture_output=True, timeout=30
        )
        subprocess.run(
            ["git", "config", "user.email", "t@t"],
            cwd=temp_workspace,
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=temp_workspace,
            check=True,
            capture_output=True,
            timeout=30,
        )

        async def scenario() -> None:
            d = Dormancy(repo=temp_workspace)
            d.no_progress = 5  # force dormant
            shutdown = asyncio.Event()
            sleep_task = asyncio.create_task(d.wait(shutdown, base_interval=60.0))
            await asyncio.sleep(0.05)
            (temp_workspace / "new.txt").write_text("hi\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "-A"],
                cwd=temp_workspace,
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-m", "wake"],
                cwd=temp_workspace,
                check=True,
                capture_output=True,
                timeout=30,
            )
            await asyncio.wait_for(sleep_task, timeout=10.0)
            assert d.no_progress == 0

        asyncio.run(scenario())


class TestSessionSlider:
    def test_ensure_opens_and_reuses(self, temp_workspace: Path) -> None:
        slider = SessionSlider()
        run = slider.ensure()
        assert run is not None and run["status"] == "running"
        again = slider.ensure()
        assert again["run_id"] == run["run_id"]

    def test_after_cycle_slides_on_incomplete(self, temp_workspace: Path) -> None:
        import contextlib

        from evolver.gep.evolution_session import EvolutionSession

        slider = SessionSlider()
        first = slider.ensure()
        assert first is not None
        # Burn the frozen budget with a reject per round; the ninth begin
        # closes the session as incomplete (budget_exhausted).
        session = EvolutionSession()
        for _ in range(int(first["budget"]["max_rounds"])):
            session.begin_round("h", "c")
            session.record_round(decision="reject", notes="n")
        with contextlib.suppress(Exception):
            session.begin_round("h", "c")
        assert EvolutionSession().latest_run()["status"] != "running"
        # Net gain afterwards → a fresh session slides open automatically.
        slider.after_cycle(promoted=True)
        renewed = EvolutionSession().latest_run()
        assert renewed["status"] == "running"
        assert renewed["run_id"] != first["run_id"]
