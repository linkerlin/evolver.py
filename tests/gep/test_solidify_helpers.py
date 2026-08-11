"""Solidify process helper contracts (v1.94.0 parity).

Behavioral port of Node ``test/solidify-helpers.test.js`` onto
:mod:`evolver.gep.solidify_helpers` + the shared validation-command gate in
:mod:`evolver.gep.policy_check`.
"""

from __future__ import annotations

from evolver.config import BLAST_RADIUS_HARD_CAP_FILES, BLAST_RADIUS_HARD_CAP_LINES
from evolver.gep.git_ops import (
    is_constraint_counted_path,
    is_critical_protected_path,
    normalize_rel_path,
)
from evolver.gep.policy_check import is_validation_command_allowed
from evolver.gep.solidify_helpers import (
    analyze_blast_radius_breakdown,
    build_failure_reason,
    classify_blast_severity,
    compare_blast_estimate,
    compute_process_scores,
    is_forbidden_path,
    pick_gene_category,
)


def scores(**overrides: object) -> dict:
    base: dict = {
        "constraint_check": {"ok": True, "violations": []},
        "validation": {"ok": True, "results": [{"ok": True, "cmd": "node test.js"}]},
        "protocol_violations": [],
        "canary": {"ok": True, "skipped": True},
        "blast": {"files": 1, "lines": 10},
        "gene_used": {"type": "Gene", "id": "gene_test", "constraints": {"max_files": 20}},
        "signals": ["error"],
        "mutation": {"rationale": "test fix", "category": "repair", "risk_level": "low"},
    }
    base.update(overrides)
    return compute_process_scores(**base)


class TestIsForbiddenPath:
    def test_blocks_exact_match(self) -> None:
        assert is_forbidden_path(".git", [".git", "node_modules"]) is True

    def test_blocks_prefix_match(self) -> None:
        assert is_forbidden_path("node_modules/dotenv/index.js", [".git", "node_modules"]) is True

    def test_allows_non_forbidden(self) -> None:
        assert is_forbidden_path("src/evolve.js", [".git", "node_modules"]) is False

    def test_handles_empty_forbidden_list(self) -> None:
        assert is_forbidden_path("src/evolve.js", []) is False


class TestClassifyBlastSeverity:
    def test_within_limit(self) -> None:
        r = classify_blast_severity(blast={"files": 3, "lines": 50}, max_files=20)
        assert r == "within_limit"

    def test_approaching_limit_above_80_percent(self) -> None:
        r = classify_blast_severity(blast={"files": 17, "lines": 100}, max_files=20)
        assert r == "approaching_limit"

    def test_exceeded_when_over_limit(self) -> None:
        r = classify_blast_severity(blast={"files": 25, "lines": 100}, max_files=20)
        assert r == "exceeded"

    def test_critical_overrun_at_2x(self) -> None:
        r = classify_blast_severity(blast={"files": 45, "lines": 100}, max_files=20)
        assert r == "critical_overrun"

    def test_hard_cap_breach_files_above_system_limit(self) -> None:
        r = classify_blast_severity(
            blast={"files": BLAST_RADIUS_HARD_CAP_FILES + 1, "lines": 0}, max_files=200
        )
        assert r == "hard_cap_breach"

    def test_hard_cap_breach_lines_above_system_limit(self) -> None:
        r = classify_blast_severity(
            blast={"files": 1, "lines": BLAST_RADIUS_HARD_CAP_LINES + 1},
            max_files=200,
            max_lines=BLAST_RADIUS_HARD_CAP_LINES,
        )
        assert r == "hard_cap_breach"


class TestAnalyzeBlastRadiusBreakdown:
    def test_groups_by_top_level_directory(self) -> None:
        files = ["src/gep/a.js", "src/gep/b.js", "src/ops/c.js", "test/d.js"]
        result = analyze_blast_radius_breakdown(files, 3)
        assert len(result) <= 3
        assert result[0]["dir"] == "src"
        assert result[0]["files"] >= 2

    def test_empty_for_no_files(self) -> None:
        assert analyze_blast_radius_breakdown([], 5) == []


class TestCompareBlastEstimate:
    def test_null_when_no_estimate(self) -> None:
        assert compare_blast_estimate(None, {"files": 5}) is None

    def test_drift_when_actual_3x(self) -> None:
        r = compare_blast_estimate({"files": 3}, {"files": 15})
        assert r is not None
        assert r["drifted"] is True

    def test_no_drift_when_close(self) -> None:
        r = compare_blast_estimate({"files": 5}, {"files": 6})
        assert r is not None
        assert r["drifted"] is False


class TestBuildFailureReason:
    def test_combines_failures(self) -> None:
        reason = build_failure_reason(
            {"violations": ["max_files exceeded"]},
            {"results": [{"ok": False, "cmd": "node test.js", "err": "exit 1"}]},
            ["missing Mutation object"],
            None,
        )
        assert "constraint: max_files exceeded" in reason
        assert "protocol: missing Mutation object" in reason
        assert "validation_failed" in reason

    def test_unknown_for_empty_inputs(self) -> None:
        assert build_failure_reason({}, {}, [], None) == "unknown"

    def test_canary_failure_included(self) -> None:
        reason = build_failure_reason({}, {"results": []}, [], {"ok": False})
        assert "canary_failed" in reason


class TestComputeProcessScores:
    def test_pass_rate_0_5_when_results_empty(self) -> None:
        assert scores(validation={"ok": True, "results": []})["validation_pass_rate"] == 0.5

    def test_pass_rate_1_0_all_pass(self) -> None:
        v = {"ok": True, "results": [{"ok": True, "cmd": "node a.js"}]}
        assert scores(validation=v)["validation_pass_rate"] == 1.0

    def test_pass_rate_0_failed_no_results(self) -> None:
        assert scores(validation={"ok": False, "results": []})["validation_pass_rate"] == 0.0

    def test_pass_rate_partial(self) -> None:
        v = {"ok": False, "results": [{"ok": True}, {"ok": False}]}
        assert scores(validation=v)["validation_pass_rate"] == 0.5

    def test_blast_control_zero_for_hollow_commit(self) -> None:
        s = scores(
            constraint_check={
                "ok": False,
                "violations": [
                    "hollow_commit: 3 file(s) changed but 0 are constraint-counted code."
                ],
            },
            blast={
                "files": 0,
                "lines": 0,
                "all_changed_files": [
                    "assets/gep/capsules.json",
                    "assets/gep/events.jsonl",
                    "assets/gep/genes.json",
                ],
            },
            signals=["evolution_stagnation_detected"],
            mutation={"rationale": "optimize", "category": "optimize"},
        )
        assert s["blast_control"] == 0.0
        assert s["hollow_commit"] is True

    def test_blast_control_one_for_real_changes(self) -> None:
        s = scores(
            blast={
                "files": 2,
                "lines": 30,
                "all_changed_files": [
                    "src/evolve.js",
                    "src/gep/solidify.py",
                    "assets/gep/events.jsonl",
                ],
            }
        )
        assert s["blast_control"] == 1.0


class TestPickGeneCategory:
    def test_returns_valid_intent(self) -> None:
        assert pick_gene_category("repair") == "repair"
        assert pick_gene_category("explore") == "explore"

    def test_falls_back_for_invalid(self) -> None:
        assert pick_gene_category("bogus") == "innovate"
        assert pick_gene_category("") == "innovate"
        assert pick_gene_category(None) == "innovate"

    def test_uses_custom_fallback(self) -> None:
        assert pick_gene_category("bogus", fallback="optimize") == "optimize"

    def test_safe_default_when_fallback_invalid(self) -> None:
        assert pick_gene_category("bogus", fallback="nope") == "innovate"


class TestValidationCommandGate:
    """Port of the isValidationCommandAllowed cluster (GHSA-jxh8-jh77-xh6g)."""

    def test_allows_node_commands(self) -> None:
        assert is_validation_command_allowed("node scripts/validate.js") is True

    def test_blocks_npm(self) -> None:
        assert is_validation_command_allowed("npm test") is False
        assert is_validation_command_allowed("npm install") is False

    def test_blocks_shell_operators(self) -> None:
        assert is_validation_command_allowed("node test.js && rm -rf /") is False
        assert is_validation_command_allowed("node test.js; echo hacked") is False

    def test_blocks_backtick_injection(self) -> None:
        assert is_validation_command_allowed("node `whoami`") is False

    def test_blocks_inline_eval(self) -> None:
        for cmd in (
            'node -e "process.exit(1)"',
            'node --eval "console.log(1)"',
            'node -p "1+1"',
            "node --print \"require('fs')\"",
        ):
            assert is_validation_command_allowed(cmd) is False, cmd

    def test_blocks_command_substitution(self) -> None:
        assert is_validation_command_allowed("node $(echo malicious).js") is False

    def test_blocks_npx(self) -> None:
        assert is_validation_command_allowed("npx vitest run") is False

    def test_allows_node_scripts_with_arguments(self) -> None:
        assert (
            is_validation_command_allowed(
                "node scripts/validate-modules.js ./src/evolve ./src/gep/solidify"
            )
            is True
        )
        assert is_validation_command_allowed("node scripts/validate-suite.js") is True

    def test_blocks_non_allowed_commands(self) -> None:
        assert is_validation_command_allowed("rm -rf /") is False
        assert is_validation_command_allowed("curl http://evil.com") is False

    def test_false_for_empty(self) -> None:
        assert is_validation_command_allowed("") is False
        assert is_validation_command_allowed(None) is False


class TestGitOpsPathHelpers:
    """Document the Python git_ops contract for the shared path helpers."""

    def test_normalize_rel_path(self) -> None:
        assert normalize_rel_path(".\\src\\evolve.js") == "src/evolve.js"
        assert normalize_rel_path("./src/evolve.js") == "src/evolve.js"
        assert normalize_rel_path("") == ""

    def test_is_critical_protected_path(self) -> None:
        # Python-ecosystem adapted list (pyproject/uv.lock instead of package.json).
        assert is_critical_protected_path(".env") is True
        assert is_critical_protected_path("pyproject.toml") is True
        assert is_critical_protected_path("uv.lock") is True
        assert is_critical_protected_path("src/evolve.js") is False

    def test_is_constraint_counted_path(self) -> None:
        assert is_constraint_counted_path("src/evolve.py") is True
        assert is_constraint_counted_path("node_modules/x/y.js") is False
        assert is_constraint_counted_path(".git/config") is False
