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

    def test_records_call_to_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
            "echo {prompt}",
            {"prompt": "subbed"},
            kind="t",
            record=False,
        )
        assert "subbed" in out


class TestBuildLlmCall:
    def test_flag_off_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "0")
        assert (
            build_llm_call("echo x", kind="t", placeholders={}) is None
        )

    def test_no_template_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "1")
        assert build_llm_call(None, kind="t", placeholders={}) is None
        assert build_llm_call("   ", kind="t", placeholders={}) is None

    def test_flag_on_runs_template(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_TEMPLATE", "1")
        monkeypatch.setenv("EVOLVER_LLM_CALL_DIR", str(tmp_path / "calls"))
        out = build_llm_call(
            "echo hi",
            kind="t",
            placeholders={},
        )
        assert out is not None
        assert "hi" in out
