"""Tests for evolver.gep.llm_template (Sprint D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.llm_template import (
    build_llm_call,
    render_template,
    run_external_template,
)


class TestRenderTemplate:
    def test_substitutes_known(self) -> None:
        out = render_template("echo {prompt}", {"prompt": "hi"})
        assert out == "echo hi"

    def test_unknown_placeholder_left(self) -> None:
        out = render_template("echo {prompt} {unknown}", {"prompt": "hi"})
        assert out == "echo hi {unknown}"

    def test_missing_placeholder_unchanged(self) -> None:
        out = render_template("echo {prompt}", {})
        assert out == "echo {prompt}"


class TestRunExternalTemplate:
    def test_returns_stdout(self) -> None:
        out = run_external_template(
            "echo hello",
            {},
            kind="t",
            record=False,
        )
        assert "hello" in out

    def test_records_call_to_disk(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        out = run_external_template(
            "echo recorded",
            {"prompt": "p1"},
            kind="diagnosis",
            record=True,
        )
        assert "recorded" in out
        in_files = list((tmp_path / "calls").glob("*_diagnosis_in.json"))
        out_files = list((tmp_path / "calls").glob("*_diagnosis_out.txt"))
        assert len(in_files) == 1
        assert len(out_files) == 1
        payload = json.loads(in_files[0].read_text(encoding="utf-8"))
        assert payload["template"] == "echo recorded"
        assert payload["placeholders"] == {"prompt": "p1"}
        assert "recorded" in out_files[0].read_text(encoding="utf-8")

    def test_placeholder_substitution_in_command(self) -> None:
        out = run_external_template(
            "echo {arg}",
            {"arg": "subbed"},
            kind="t",
            record=False,
        )
        assert "subbed" in out


class TestInjectionGuard:
    """P2 (演进方案.md §11.4 #5): naked free-text rejected by placeholder identity."""

    def test_refuses_naked_free_text_by_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        # Even completely benign text is refused because {prompt} is a free-text
        # placeholder identity.
        out = run_external_template(
            "echo {prompt}",
            {"prompt": "plain benign text"},
            kind="t",
            record=True,
        )
        assert out == ""
        refused = list((tmp_path / "calls").glob("*_t_refused.txt"))
        assert len(refused) == 1, "refusal must leave an audit marker"
        message = refused[0].read_text(encoding="utf-8")
        assert "raw free-text placeholder '{prompt}'" in message
        assert "{prompt_file}" in message

    def test_refuses_naked_diagnosis_and_response(self) -> None:
        out_diag = run_external_template(
            "echo {diagnosis}",
            {"diagnosis": "diagnostic text"},
            kind="t",
            record=False,
        )
        assert out_diag == ""
        out_resp = run_external_template(
            "echo {response}",
            {"response": "response text"},
            kind="t",
            record=False,
        )
        assert out_resp == ""

    def test_refuses_non_free_text_command_substitution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        out = run_external_template(
            "echo {model}",
            {"model": "gpt-`whoami`"},
            kind="t",
            record=True,
        )
        assert out == ""
        refused = list((tmp_path / "calls").glob("*_t_refused.txt"))
        assert len(refused) == 1
        assert "command-substitution construct" in refused[0].read_text(encoding="utf-8")

    def test_file_passed_value_runs(self) -> None:
        # File path placeholder passes through safely
        out = run_external_template(
            "echo {prompt_file}",
            {"prompt_file": "calls/x_in.json"},
            kind="t",
            record=False,
        )
        assert "calls/x_in.json" in out

    def test_auto_materialize_prompt_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        out = run_external_template(
            "cat {prompt_file}",
            {"prompt": "content to materialize"},
            kind="t",
            record=True,
        )
        assert "content to materialize" in out
        mat_files = list((tmp_path / "calls").glob("*_prompt.txt"))
        assert len(mat_files) == 1
        assert mat_files[0].read_text(encoding="utf-8") == "content to materialize"


class TestAnchorInterlock:
    """§11.4 #5: enable_llm_template is interlocked with ANCHOR_TRIGGER_SURFACES."""

    def test_refuses_when_surface_not_in_anchor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        import evolver.config as cfg
        from evolver.gep.feature_flags import is_enabled

        # Strip llm_template.py from anchor surfaces
        surfaces = tuple(s for s in cfg.ANCHOR_TRIGGER_SURFACES if "llm_template" not in s)
        monkeypatch.setattr(cfg, "ANCHOR_TRIGGER_SURFACES", surfaces)

        # 1. Feature flag refuses to enable
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "1")
        assert is_enabled("enable_llm_template") is False

        # 2. build_llm_call returns None
        assert build_llm_call("echo safe", kind="t", placeholders={}) is None

        # 3. run_external_template refuses and records audit marker
        out = run_external_template("echo safe", {}, kind="t", record=True)
        assert out == ""
        refused = list((tmp_path / "calls").glob("*_t_refused.txt"))
        assert len(refused) == 1
        assert "interlock failed" in refused[0].read_text(encoding="utf-8")


class TestBuildLlmCall:
    def test_flag_off_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "0")
        assert build_llm_call("echo x", kind="t", placeholders={}) is None

    def test_no_template_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "1")
        assert build_llm_call(None, kind="t", placeholders={}) is None
        assert build_llm_call("   ", kind="t", placeholders={}) is None

    def test_flag_on_runs_template(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "1")
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        out = build_llm_call(
            "echo hi",
            kind="t",
            placeholders={},
        )
        assert out is not None
        assert "hi" in out
