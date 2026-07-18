"""Tests for evolver.gep.validation_report.

Ports Node's ``test/validationReport.test.js`` (17 contracts).
"""

from __future__ import annotations

from evolver.gep.validation_report import (
    build_validation_report,
    is_valid_validation_report,
)


class TestBuildValidationReport:
    def test_builds_valid_report_with_minimal_input(self) -> None:
        report = build_validation_report(
            gene_id="gene_test",
            commands=["echo hello"],
            results=[{"ok": True, "stdout": "hello", "stderr": ""}],
        )
        assert report["type"] == "ValidationReport"
        assert report["gene_id"] == "gene_test"
        assert report["overall_ok"] is True
        assert len(report["commands"]) == 1
        assert report["commands"][0]["command"] == "echo hello"
        assert report["commands"][0]["ok"] is True
        assert str(report["id"]).startswith("vr_")
        assert report["created_at"]
        assert report["asset_id"]
        assert report["env_fingerprint"]
        assert report["env_fingerprint_key"]

    def test_marks_overall_ok_false_when_any_result_fails(self) -> None:
        report = build_validation_report(
            gene_id="gene_fail",
            commands=["cmd1", "cmd2"],
            results=[
                {"ok": True, "stdout": "ok"},
                {"ok": False, "stderr": "error"},
            ],
        )
        assert report["overall_ok"] is False

    def test_marks_overall_ok_false_when_results_empty(self) -> None:
        report = build_validation_report(
            gene_id="gene_empty",
            commands=[],
            results=[],
        )
        assert report["overall_ok"] is False

    def test_handles_null_gene_id(self) -> None:
        report = build_validation_report(
            commands=["test"],
            results=[{"ok": True}],
        )
        assert report["gene_id"] is None

    def test_computes_duration_ms_from_timestamps(self) -> None:
        report = build_validation_report(
            gene_id="gene_dur",
            commands=["test"],
            results=[{"ok": True}],
            started_at=1000,
            finished_at=2500,
        )
        assert report["duration_ms"] == 1500

    def test_duration_ms_null_when_timestamps_missing(self) -> None:
        report = build_validation_report(
            gene_id="gene_nodur",
            commands=["test"],
            results=[{"ok": True}],
        )
        assert report["duration_ms"] is None

    def test_truncates_stdout_stderr_to_4000_chars(self) -> None:
        long_output = "x" * 5000
        report = build_validation_report(
            gene_id="gene_long",
            commands=["test"],
            results=[{"ok": True, "stdout": long_output, "stderr": long_output}],
        )
        assert len(report["commands"][0]["stdout"]) == 4000
        assert len(report["commands"][0]["stderr"]) == 4000

    def test_supports_out_stdout_and_err_stderr_field_names(self) -> None:
        report = build_validation_report(
            gene_id="gene_compat",
            commands=["test"],
            results=[{"ok": True, "out": "output_via_out", "err": "error_via_err"}],
        )
        assert report["commands"][0]["stdout"] == "output_via_out"
        assert report["commands"][0]["stderr"] == "error_via_err"

    def test_infers_commands_from_results_when_commands_not_provided(self) -> None:
        report = build_validation_report(
            gene_id="gene_infer",
            results=[{"ok": True, "cmd": "inferred_cmd"}],
        )
        assert report["commands"][0]["command"] == "inferred_cmd"

    def test_uses_provided_env_fp_instead_of_capturing(self) -> None:
        custom_fp = {"device_id": "custom", "platform": "test"}
        report = build_validation_report(
            gene_id="gene_fp",
            commands=["test"],
            results=[{"ok": True}],
            env_fp=custom_fp,
        )
        assert report["env_fingerprint"]["device_id"] == "custom"


class TestIsValidValidationReport:
    def test_returns_true_for_valid_report(self) -> None:
        report = build_validation_report(
            gene_id="gene_valid",
            commands=["test"],
            results=[{"ok": True}],
        )
        assert is_valid_validation_report(report) is True

    def test_returns_false_for_null(self) -> None:
        assert is_valid_validation_report(None) is False

    def test_returns_false_for_non_object(self) -> None:
        assert is_valid_validation_report("string") is False

    def test_returns_false_for_wrong_type_field(self) -> None:
        assert (
            is_valid_validation_report(
                {"type": "Other", "id": "x", "commands": [], "overall_ok": True}
            )
            is False
        )

    def test_returns_false_for_missing_id(self) -> None:
        assert (
            is_valid_validation_report(
                {"type": "ValidationReport", "commands": [], "overall_ok": True}
            )
            is False
        )

    def test_returns_false_for_missing_commands(self) -> None:
        assert (
            is_valid_validation_report({"type": "ValidationReport", "id": "x", "overall_ok": True})
            is False
        )

    def test_returns_false_for_missing_overall_ok(self) -> None:
        assert (
            is_valid_validation_report({"type": "ValidationReport", "id": "x", "commands": []})
            is False
        )
