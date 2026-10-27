"""Comprehensive test suite for Harness2 (arXiv:2610.14224v1) mechanical harnesses H2-1..H2-6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.bench.runner import prepare_paired_library_solves, verify_solve_receipt
from evolver.gep import episode_record, library, record_route, working_memory
from evolver.gep.distill import distill_text, install_distilled
from evolver.gep.policy_check import (
    COMPONENT_COST_HIERARCHY,
    check_deliverable_conformance,
    check_policy,
    validate_harness_component_integrity,
)
from evolver.gep.proposal import compose_proposals
from evolver.gep.skill2gep_audit import (
    audit_workspace_fact_leakage,
    validate_transferable_experience,
)
from evolver.gep.variant_archive import salvageable_semantic_variants, variant_entry
from evolver.ops.meta_report import build_meta_report, library_provenance_panel

# ---------------------------------------------------------------------------
# H2-1: Four-Way Component Attribution & Confounded Distillation Guard
# ---------------------------------------------------------------------------


def test_single_component_helped_attribution() -> None:
    diff = "diff --git a/scripts/verify.py b/scripts/verify.py\n+assert True\n"
    checks = [{"command": "pytest", "ok": True}]
    attr = episode_record.compute_component_attribution(
        diff,
        checks,
        outcome={"status": "success", "score": 1.0},
    )
    assert attr["status"] == "helped"
    assert attr["confounded"] is False
    assert attr["eligible_for_experience"] is True
    assert attr["touched_count"] == 1
    assert attr["components"][0]["component"] == "scripts/verify.py"
    assert attr["components"][0]["group"] == "script"
    assert attr["components"][0]["verdict"] == "helped"


def test_single_component_hurt_and_no_observed_effect_attribution() -> None:
    diff = "diff --git a/skills/audit/SKILL.md b/skills/audit/SKILL.md\n+# rule\n"
    hurt_attr = episode_record.compute_component_attribution(
        diff,
        [{"command": "pytest", "ok": False}],
        outcome={"status": "failed", "score": 0.0},
    )
    assert hurt_attr["status"] == "hurt"
    assert hurt_attr["confounded"] is False
    assert hurt_attr["eligible_for_experience"] is False

    flat_attr = episode_record.compute_component_attribution(
        diff,
        [{"command": "pytest", "ok": True}],
        outcome={"status": "failed", "score": 0.5, "pack_reason": "flat"},
    )
    assert flat_attr["status"] == "no_observed_effect"
    assert flat_attr["confounded"] is False
    assert flat_attr["eligible_for_experience"] is False


def test_multi_component_edit_is_marked_confounded() -> None:
    diff = (
        "diff --git a/skills/audit/SKILL.md b/skills/audit/SKILL.md\n+# skill\n"
        "diff --git a/scripts/check_totals.py b/scripts/check_totals.py\n+print(1)\n"
    )
    attr = episode_record.compute_component_attribution(
        diff,
        [{"command": "pytest", "ok": True}],
        outcome={"status": "success", "score": 1.0},
    )
    assert attr["status"] == "confounded"
    assert attr["confounded"] is True
    assert attr["eligible_for_experience"] is False
    assert attr["touched_count"] == 2
    assert [c["verdict"] for c in attr["components"]] == ["confounded", "confounded"]


def test_attach_attribution_preserves_legacy_render_when_absent() -> None:
    base_body = {
        "run_id": "run_h2",
        "gene": {"id": "gene_h2"},
        "outcome": {"status": "success", "score": 1.0},
        "gates": {"acceptance": {"accepted": True}},
        "checks": [{"command": "pytest", "ok": True}],
        "diff": "diff --git a/scripts/a.py b/scripts/a.py\n+x = 1\n",
    }
    legacy_rendered = episode_record.render_episode_block(base_body, ep_id="ep_h2")
    assert "attribution:" not in legacy_rendered

    enriched = episode_record.attach_component_attribution(base_body)
    rendered = episode_record.render_episode_block(enriched, ep_id="ep_h2")
    expected_line = "- attribution: status=helped confounded=False eligible_for_experience=True"
    assert expected_line in rendered
    assert rendered.replace(expected_line + "\n", "") == legacy_rendered


def test_distill_filters_confounded_genes_from_durable_library(temp_workspace: Path) -> None:
    raw_response = """```json
{
  "type": "Gene",
  "id": "gene_confounded_test",
  "category": "repair",
  "signals_match": ["reconciliation_mismatch"],
  "strategy": ["Add a verification script under scripts/check.py"],
  "validation": ["python --version"]
}
```"""
    distilled = distill_text(raw_response)
    assert len(distilled["genes"]) == 1

    confounded_attr = {
        "status": "confounded",
        "confounded": True,
        "eligible_for_experience": False,
    }
    res = install_distilled(distilled, attribution=confounded_attr)
    assert res["ok"] is True
    assert res["installed"] == []
    assert len(res["skipped_genes"]) == 1
    assert res["skipped_genes"][0]["reason"] == "confounded_or_ineligible_attribution"


# ---------------------------------------------------------------------------
# H2-2: Transferable Experience Triad & Workspace-Fact Isolation Gate
# ---------------------------------------------------------------------------


def test_working_memory_formats_and_extracts_workspace_facts(temp_workspace: Path) -> None:
    section = working_memory.format_workspace_facts_section(
        [
            "parser bug is in src/parser.py line 42",
            "in this workspace: active task is train-03",
        ],
        ruled_out=["regex fallback broke header row"],
    )
    working_memory.write_working(section)
    facts = working_memory.extract_workspace_facts()
    assert facts == [
        "parser bug is in src/parser.py line 42",
        "active task is train-03",
    ]
    cleared = working_memory.archive_and_clear("accept")
    assert cleared["cleared"] is True
    assert not working_memory.working_path().exists()


def test_audit_workspace_fact_leakage_catches_all_four_leak_classes() -> None:
    contaminated = {
        "type": "Gene",
        "id": "gene_leaky",
        "summary": "In this workspace we fixed train-04 at /tmp/sandbox/f.py line 88",
        "signals_match": ["log_error"],
        "strategy": ["Patch file.py:L12-L20"],
    }
    report = audit_workspace_fact_leakage(contaminated)
    assert report["clean"] is False
    rules = {v["rule"] for v in report["violations"]}
    assert "explicit_workspace_fact" in rules
    assert "temp_sandbox_path" in rules
    assert "benchmark_instance_id" in rules
    assert "bare_line_anchor" in rules
    assert "WORKING_SESSION.md" in report["steer_message"]


def test_validate_transferable_experience_triad_and_no_entry() -> None:
    no_entry = validate_transferable_experience({"action": "NO_ENTRY"})
    assert no_entry["ok"] is True
    assert no_entry["no_entry"] is True

    valid_gene = {
        "type": "Gene",
        "id": "gene_clean_skill",
        "category": "repair",
        "signals_match": ["csv_header_drift"],
        "strategy": ["Add a deterministic verification script under scripts/check_headers.py"],
        "validation": ["python --version"],
    }
    verdict = validate_transferable_experience(valid_gene)
    assert verdict["ok"] is True
    assert verdict["eligible"] is True

    incomplete = {
        "type": "Gene",
        "id": "gene_vague",
        "signals_match": [],
        "strategy": ["Be more careful and double check everything"],
    }
    bad = validate_transferable_experience(incomplete)
    assert bad["ok"] is False
    assert bad["reason"] == "incomplete_experience_triad"


def test_install_distilled_strict_transferable_blocks_contaminated_gene(
    temp_workspace: Path,
) -> None:
    leaky_gene = {
        "type": "Gene",
        "id": "gene_ws_leak",
        "category": "repair",
        "signals_match": ["err"],
        "strategy": ["In this workspace edit scripts/fix.py line 15"],
        "validation": ["python --version"],
    }
    clean_gene = {
        "type": "Gene",
        "id": "gene_clean_transfer",
        "category": "repair",
        "signals_match": ["err"],
        "strategy": ["Add a reusable validator script under scripts/validate_schema.py"],
        "validation": ["python --version"],
    }
    res = install_distilled(
        {"genes": [leaky_gene, clean_gene], "capsules": []},
        strict_transferable=True,
    )
    assert [g["id"] for g in res["installed"]] == ["gene_clean_transfer"]
    assert len(res["skipped_genes"]) == 1
    assert res["skipped_genes"][0]["id"] == "gene_ws_leak"
    assert res["skipped_genes"][0]["reason"] == "workspace_fact_leakage"


# ---------------------------------------------------------------------------
# H2-3: INV x DOM Orthogonal Scopes & Mechanical Selective Composer
# ---------------------------------------------------------------------------


def test_inv_and_dom_scope_validation() -> None:
    inv_check = record_route.validate_proposal_scope(
        "INV",
        ["scripts/check_output.py", "plugin/pre_commit_hook.py", "src/domain_ledger.py"],
    )
    assert inv_check["ok"] is False
    assert inv_check["dimension"] == "tool"
    assert "scripts/check_output.py" in inv_check["allowed_files"]
    assert "plugin/pre_commit_hook.py" in inv_check["allowed_files"]
    assert inv_check["out_of_scope_files"] == ["src/domain_ledger.py"]

    dom_check = record_route.validate_proposal_scope(
        "DOM",
        ["skills/accounting/SKILL.md", "src/domain_ledger.py", "scripts/check_output.py"],
    )
    assert dom_check["ok"] is False
    assert dom_check["dimension"] == "content"
    assert "skills/accounting/SKILL.md" in dom_check["allowed_files"]
    assert "src/domain_ledger.py" in dom_check["allowed_files"]
    assert dom_check["out_of_scope_files"] == ["scripts/check_output.py"]


def test_scoped_direction_prompt_renders_role_and_dimension() -> None:
    prompt_inv = record_route.build_scoped_direction_prompt(
        "INV", {"id": "sha256:aaa"}, {"id": "sha256:bbb"}
    )
    assert "scope_role: `INV`" in prompt_inv
    assert "hypothesis_dimension: `tool`" in prompt_inv

    prompt_dom = record_route.build_scoped_direction_prompt(
        "DOM", {"id": "sha256:bbb"}, {"id": "sha256:aaa"}
    )
    assert "scope_role: `DOM`" in prompt_dom
    assert "hypothesis_dimension: `content`" in prompt_dom


def test_compose_proposals_merges_orthogonal_inv_and_dom_and_drops_bad_candidates(
    temp_workspace: Path,
) -> None:
    (temp_workspace / "scripts").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "scripts" / "verify.py").write_text("STRICT = False\n", encoding="utf-8")
    (temp_workspace / "src").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "src" / "domain.py").write_text("TOLERANCE = 0.1\n", encoding="utf-8")

    candidates = [
        {
            "candidate_id": "cand_inv",
            "role": "INV",
            "verdict": "helped",
            "evidence": "verify.py caught formatting drift on task-1",
            "proposal": {
                "action": "patch",
                "gene_id": "gene_comp",
                "edits": [
                    {
                        "op": "replace",
                        "file": "scripts/verify.py",
                        "target": "STRICT = False",
                        "content": "STRICT = True",
                    },
                    # Out-of-scope edit by INV into domain business file -> must be dropped
                    {
                        "op": "replace",
                        "file": "src/domain.py",
                        "target": "TOLERANCE = 0.1",
                        "content": "TOLERANCE = 999.0",
                    },
                ],
            },
        },
        {
            "candidate_id": "cand_dom",
            "role": "DOM",
            "verdict": "helped",
            "evidence": "reconciliation passed after tightening tolerance",
            "proposal": {
                "action": "patch",
                "gene_id": "gene_comp",
                "edits": [
                    {
                        "op": "replace",
                        "file": "src/domain.py",
                        "target": "TOLERANCE = 0.1",
                        "content": "TOLERANCE = 0.01",
                    }
                ],
            },
        },
        {
            "candidate_id": "cand_hurt",
            "role": "DOM",
            "verdict": "hurt",
            "evidence": "regressed 2 checks",
            "proposal": {
                "action": "patch",
                "edits": [
                    {
                        "op": "append",
                        "file": "src/domain.py",
                        "content": "\nBROKEN = True\n",
                    }
                ],
            },
        },
        {
            "candidate_id": "cand_nondelivering",
            "role": "INV",
            "verdict": "helped",
            "non_delivering": True,
            "proposal": {
                "action": "patch",
                "edits": [
                    {
                        "op": "append",
                        "file": "scripts/verify.py",
                        "content": "\n# ghost\n",
                    }
                ],
            },
        },
    ]

    result = compose_proposals(candidates, root=temp_workspace, apply=True)
    assert result["ok"] is True
    assert result["decision"] == "composed"
    assert result["kept_count"] == 2
    assert result["dropped_count"] == 3
    assert result["apply_report"]["applied"] is True
    assert (temp_workspace / "scripts" / "verify.py").read_text(
        encoding="utf-8"
    ) == "STRICT = True\n"
    assert (temp_workspace / "src" / "domain.py").read_text(
        encoding="utf-8"
    ) == "TOLERANCE = 0.01\n"


def test_compose_proposals_returns_keep_base_when_all_candidates_rejected(
    temp_workspace: Path,
) -> None:
    res = compose_proposals(
        [
            {
                "candidate_id": "c1",
                "verdict": "confounded",
                "proposal": {
                    "action": "patch",
                    "edits": [{"op": "append", "file": "a.py", "content": "x = 1\n"}],
                },
            }
        ],
        root=temp_workspace,
        apply=True,
    )
    assert res["decision"] == "keep_base"
    assert res["proposal"].action == "no_action"
    assert res["apply_report"]["applied"] is False


def test_salvageable_semantic_variants_recovers_clean_single_component_variant() -> None:
    single_diff = "diff --git a/scripts/check.py b/scripts/check.py\n+x = 1\n"
    multi_diff = (
        "diff --git a/scripts/a.py b/scripts/a.py\n+x = 1\n"
        "diff --git a/src/b.py b/src/b.py\n+y = 2\n"
    )
    e1 = variant_entry(
        {
            "run_id": "r1",
            "gene_id": "g1",
            "signals": ["log_error:parse"],
            "diff_snapshot": single_diff,
            "outcome": {"status": "failed", "error": "missing_domain_rule"},
        },
        "semantic",
    )
    e2 = variant_entry(
        {
            "run_id": "r2",
            "gene_id": "g1",
            "signals": ["log_error:parse"],
            "diff_snapshot": multi_diff,
            "outcome": {"status": "failed", "error": "missing_domain_rule"},
        },
        "semantic",
    )
    assert e1 is not None and e2 is not None
    later_events = [
        {
            "id": "evt_later",
            "signals": ["log_error:format"],
            "outcome": {"status": "failed", "error": "header_mismatch"},
        }
    ]
    salvaged = salvageable_semantic_variants([e1, e2], ["log_error:now"], later_events)
    assert len(salvaged) == 1
    assert salvaged[0]["variant_id"] == e1["variant_id"]
    assert salvaged[0]["isolated_component"] == "scripts/check.py"


# ---------------------------------------------------------------------------
# H2-4: Component Cost Hierarchy & Three-Rule Pre-Rollout Integrity Gate
# ---------------------------------------------------------------------------


def test_three_rule_component_integrity_and_cost_hierarchy(temp_workspace: Path) -> None:
    assert COMPONENT_COST_HIERARCHY == (
        "skill",
        "script",
        "subagent",
        "hook",
        "always_on_text",
    )
    # 1. Create AGENTS.md with raw template braces and no mention of 'orphan-skill'
    (temp_workspace / "AGENTS.md").write_text(
        "# System Rules\nAlways use {{ raw_jinja_var }} in prompts.\n",
        encoding="utf-8",
    )
    # 2. Create a skill whose frontmatter name mismatches its directory and references
    #    both a missing script and a syntax-broken script
    skill_dir = temp_workspace / "skills" / "orphan-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: wrong-name\ndescription: ""\n---\n'
        "Run `scripts/missing_tool.py` and `scripts/broken_tool.py`.\n",
        encoding="utf-8",
    )
    scripts_dir = temp_workspace / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "broken_tool.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    bloated_diff = "diff --git a/AGENTS.md b/AGENTS.md\n+++ b/AGENTS.md\n" + "\n".join(
        f"+{'x' * 80}" for _ in range(20)
    )

    report = validate_harness_component_integrity(
        temp_workspace,
        ["AGENTS.md", "skills/orphan-skill/SKILL.md"],
        diff_text=bloated_diff,
        check_template_braces=True,
        require_skill_trigger=True,
        max_always_on_growth_chars=500,
    )
    assert report["ok"] is False
    rules = {v.rule for v in report["violations"]}
    assert "skill_frontmatter_name_mismatch" in rules
    assert "skill_frontmatter_missing_description" in rules
    assert "unreachable_skill_trigger" in rules
    assert "missing_referenced_script" in rules
    assert "referenced_script_syntax_error" in rules
    assert "raw_template_braces" in rules
    assert "always_on_prose_bloat" in rules


def test_clean_skill_and_script_pass_component_integrity(temp_workspace: Path) -> None:
    (temp_workspace / "AGENTS.md").write_text(
        "# System Rules\nUse `reconcile-skill` when auditing. Code: `{{ safe_in_code }}`.\n",
        encoding="utf-8",
    )
    skill_dir = temp_workspace / "skills" / "reconcile-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reconcile-skill\ndescription: Reconcile ledger balances\n---\n"
        "Execute `scripts/reconcile_check.py` before finishing.\n",
        encoding="utf-8",
    )
    scripts_dir = temp_workspace / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "reconcile_check.py").write_text(
        "import sys\nsys.exit(0)\n",
        encoding="utf-8",
    )

    report = validate_harness_component_integrity(
        temp_workspace,
        ["AGENTS.md", "skills/reconcile-skill/SKILL.md"],
        diff_text="diff --git a/AGENTS.md b/AGENTS.md\n+Use `reconcile-skill`.\n",
    )
    assert report["ok"] is True
    assert report["violations"] == []

    policy = check_policy(
        changed_files=["skills/reconcile-skill/SKILL.md"],
        untracked_files=[],
        check_component_integrity=True,
    )
    assert policy.ok is True


# ---------------------------------------------------------------------------
# H2-5: Behavioral Contrast Telemetry & 6-Axis Deliverable Conformance
# ---------------------------------------------------------------------------


def test_compute_behavioral_contrast_tracks_transitions_and_error_delta() -> None:
    baseline = [
        {"command": "pytest tests/test_a.py", "ok": False},
        {"command": "pytest tests/test_b.py", "ok": True},
        {"command": "pytest tests/test_c.py", "ok": False},
    ]
    current = [
        {"command": "pytest tests/test_a.py", "ok": True},  # newly_passed
        {"command": "pytest tests/test_b.py", "ok": False},  # regressed
        {"command": "pytest tests/test_c.py", "ok": False},  # persistent_failed
    ]
    contrast = episode_record.compute_behavioral_contrast(
        current,
        baseline,
        diff_text="+fixed test_a\n",
        tool_calls=20,
        tool_errors=2,
        baseline_tool_error_rate=0.25,
    )
    trans = contrast["check_transitions"]
    assert trans["newly_passed"] == ["pytest tests/test_a.py"]
    assert trans["regressed"] == ["pytest tests/test_b.py"]
    assert trans["persistent_failed"] == ["pytest tests/test_c.py"]
    assert contrast["tool_error_rate"] == 0.1
    assert contrast["tool_error_delta"] == -0.15
    assert contrast["non_delivering"] is False

    empty_contrast = episode_record.compute_behavioral_contrast([], [], diff_text="")
    assert empty_contrast["non_delivering"] is True


def test_check_deliverable_conformance_six_axes() -> None:
    good = (
        "# Quarterly Reconciliation\n"
        "## Summary\n"
        "net_balance: 1250\n"
        "## Detail\n"
        "All GAAP entries verified.\n"
    )
    ok_res = check_deliverable_conformance(
        good,
        required_headers=["# Quarterly Reconciliation"],
        required_sections=["## Summary", "## Detail"],
        required_terms=["GAAP"],
        expected_key_values={"net_balance": 1250},
    )
    assert ok_res["ok"] is True
    assert ok_res["failed_axes"] == []

    bad = (
        "## Detail\n"
        "## Summary\n"
        "net_balance: 999\n"
        "total = =SUM(A1:A10)\n"
        "TODO: finish reconciliation\n"
    )
    bad_res = check_deliverable_conformance(
        bad,
        required_headers=["# Quarterly Reconciliation"],
        required_sections=["## Summary", "## Detail"],
        required_terms=["GAAP"],
        expected_key_values={"net_balance": 1250},
    )
    assert bad_res["ok"] is False
    assert set(bad_res["failed_axes"]) == {
        "conformance",
        "fidelity",
        "internal_consistency",
        "operational_fitness",
        "finish",
    }


# ---------------------------------------------------------------------------
# H2-6: Two-Level Recursion (H_0 + R_t) Paired Solves & Library Provenance
# ---------------------------------------------------------------------------


def test_prepare_paired_library_solves_resets_h0_and_preserves_active_pointer(
    temp_workspace: Path,
) -> None:
    parent_payload = {
        "genes": [
            {
                "id": "gene_parent",
                "summary": "Parent baseline guidance",
                "strategy": ["Check schema headers first"],
            }
        ]
    }
    candidate_payload = {
        "genes": [
            {
                "id": "gene_candidate_r_t",
                "summary": "Candidate R_t reusable verifier",
                "strategy": ["Run scripts/verify_reconciliation.py before final output"],
            }
        ]
    }
    parent_info = library.establish_parent_library(parent_payload)
    assert library.active_snapshot_id() is None

    pack_file = temp_workspace / "pack.json"
    pack_file.write_text(
        json.dumps(
            {
                "pack_version": 1,
                "tasks": [
                    {
                        "id": "train-01",
                        "split": "train",
                        "title": "Reconcile ledger",
                        "prompt": "Compute total into out.txt.",
                        "sandbox": {"input.txt": "10\n20\n"},
                        "grader": {"type": "exact", "file": "out.txt", "expected": "30"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    paired = prepare_paired_library_solves(
        pack_file,
        candidate_payload=candidate_payload,
    )
    assert paired["ok"] is True
    assert paired["parent_snapshot"] == parent_info["snapshot"]
    assert paired["candidate_snapshot"] != parent_info["snapshot"]
    assert paired["active_unchanged"] is True
    assert library.active_snapshot_id() is None

    row = paired["tasks"][0]
    assert "Parent baseline guidance" in row["parent_prompt"]
    assert "Candidate R_t reusable verifier" in row["candidate_prompt"]
    assert row["parent_receipt"]["library"] == parent_info["snapshot"]
    assert row["candidate_receipt"]["library"] == paired["candidate_snapshot"]

    verified = verify_solve_receipt(
        pack_file,
        "train-01",
        expected_library=paired["candidate_snapshot"],
    )
    assert verified["ok"] is True


def test_library_provenance_panel_classifies_direct_copy_adapted_and_novel() -> None:
    lib_entries = [
        {
            "id": "gene_reconcile",
            "summary": "Verify decimal precision and header order in CSV output",
            "strategy": [
                "def validate_csv_headers(rows, expected_columns):\n"
                "    return list(rows[0].keys()) == list(expected_columns)"
            ],
        }
    ]
    events = [
        {
            "id": "ev_direct",
            "outcome": {"status": "success"},
            "signals": ["csv_error"],
            "diff_snapshot": (
                "diff --git a/scripts/check.py b/scripts/check.py\n"
                "+def validate_csv_headers(rows, expected_columns):\n"
                "+    return list(rows[0].keys()) == list(expected_columns)\n"
            ),
        },
        {
            "id": "ev_adapted",
            "outcome": {"status": "success"},
            "signals": ["csv_error"],
            "diff_snapshot": (
                "diff --git a/scripts/check.py b/scripts/check.py\n"
                "+def validate_csv_headers(table_rows, required_cols):\n"
                "+    assert len(table_rows) > 0\n"
                "+    return tuple(table_rows[0].keys()) == tuple(required_cols)\n"
                "+    # custom adaptation for multi-sheet reconciliation\n"
            ),
        },
        {
            "id": "ev_novel",
            "outcome": {"status": "failed"},
            "signals": ["timeout_error"],
            "diff_snapshot": (
                "diff --git a/src/net.py b/src/net.py\n"
                "+SOCKET_BACKOFF_SECONDS = 45.0\n"
                "+MAX_HTTP_POOL_CONNECTIONS = 16\n"
            ),
        },
    ]
    panel = library_provenance_panel(events, lib_entries)
    assert panel["evaluated_events"] == 3
    assert panel["origins"]["direct_copy"] == 1
    assert panel["origins"]["adapted"] == 1
    assert panel["origins"]["novel"] == 1
    assert panel["library_backed_events"] == 2
    assert panel["library_backed_rate"] == 0.667
    assert panel["success_rate_by_origin"]["direct_copy"] == 1.0
    assert panel["success_rate_by_origin"]["adapted"] == 1.0
    assert panel["success_rate_by_origin"]["novel"] == 0.0

    full_report = build_meta_report(events, [], library_entries=lib_entries)
    assert full_report["panel"]["library_provenance"]["library_backed_events"] == 2


# ---------------------------------------------------------------------------
# End-to-End Pipeline / Swarm / CLI Wiring Tests
# ---------------------------------------------------------------------------


def test_attribution_note_is_separate_from_render_episode_block_and_computed_on_demand(
    temp_workspace: Path,
) -> None:
    import pytest as _pytest

    _ = _pytest
    diff = (
        "diff --git a/skills/s1/SKILL.md b/skills/s1/SKILL.md\n+++ b/skills/s1/SKILL.md\n+rule\n"
        "diff --git a/scripts/run.py b/scripts/run.py\n+++ b/scripts/run.py\n+code\n"
    )
    scene_payload = {
        "event": {
            "id": "evt_attr_1",
            "run_id": "run_attr_1",
            "timestamp": "2026-10-26T00:00:00Z",
            "gene_id": "gene_attr",
            "mutation": {"id": "mut_attr", "category": "repair"},
            "outcome": {"status": "success", "score": 1.0},
            "diff_snapshot": diff,
        },
        "validation_result": {
            "ok": True,
            "results": [{"command": "pytest", "ok": True, "stdout": "ok", "stderr": ""}],
        },
        "gate": {"accepted": True},
    }
    body = episode_record.build_episode(scene_payload)
    # Legacy render_episode_block remains untouched when gates.attribution is absent
    block = episode_record.render_episode_block(body, ep_id="ep_test")
    assert "- attribution:" not in block
    # attribution_note computes 4-way attribution on demand for dispatch.py
    note = episode_record.attribution_note(body)
    assert note == (
        "- attribution: status=confounded confounded=True eligible_for_experience=False"
    )
    # Empty diff with no target_hook returns empty string
    scene_payload["event"]["diff_snapshot"] = ""
    empty_body = episode_record.build_episode(scene_payload)
    assert episode_record.attribution_note(empty_body) == ""


def test_swarm_propose_supports_selective_composition_and_component_integrity(
    temp_workspace: Path,
) -> None:
    from evolver.swarm import swarm_propose

    inv_file = temp_workspace / "AGENTS.md"
    inv_file.write_text("# Guardrails\nline_inv = 1\n", encoding="utf-8")
    dom_file = temp_workspace / "skills" / "tax" / "SKILL.md"
    dom_file.parent.mkdir(parents=True, exist_ok=True)
    dom_file.write_text(
        "---\nname: tax\ndescription: Tax skill\n---\nline_dom = 1\n",
        encoding="utf-8",
    )

    res = swarm_propose(
        {
            "gene_id": "gene_swarm_composed",
            "check_component_integrity": True,
            "candidates": [
                {
                    "candidate_id": "cand_inv_1",
                    "role": "INV",
                    "verdict": "helped",
                    "proposal": {
                        "action": "patch",
                        "gene_id": "gene_swarm_composed",
                        "edits": [
                            {
                                "op": "replace",
                                "file": "AGENTS.md",
                                "target": "line_inv = 1",
                                "content": "line_inv = 2\nUse `tax` skill.",
                            }
                        ],
                    },
                },
                {
                    "candidate_id": "cand_dom_hurt",
                    "role": "DOM",
                    "verdict": "hurt",
                    "proposal": {
                        "action": "patch",
                        "gene_id": "gene_swarm_composed",
                        "edits": [
                            {
                                "op": "replace",
                                "file": "skills/tax/SKILL.md",
                                "target": "line_dom = 1",
                                "content": "line_dom = 2",
                            }
                        ],
                    },
                },
            ],
        }
    )
    assert res["ok"] is True
    assert res["decision"] == "composed"
    assert res["files_changed"] == ["AGENTS.md"]
    assert res["component_integrity"]["ok"] is True
    assert "line_inv = 2" in inv_file.read_text(encoding="utf-8")
    assert "line_dom = 1" in dom_file.read_text(encoding="utf-8")


def test_swarm_distill_enforces_strict_transferable_and_confounded_filter(
    temp_workspace: Path,
) -> None:
    from evolver.swarm import swarm_distill

    raw_response = (
        "Distilled candidate:\n"
        "```json\n"
        + json.dumps(
            {
                "type": "Gene",
                "id": "gene_swarm_test",
                "category": "repair",
                "signals_match": ["csv_mismatch"],
                "summary": "CUE: CSV mismatch. LESSON: Check column order.",
                "strategy": ["Verify column headers match schema before writing rows"],
                "validation": ["pytest -q"],
            }
        )
        + "\n```\n"
    )
    confounded_res = swarm_distill(
        raw_response,
        attribution={"status": "confounded", "confounded": True},
    )
    assert confounded_res["ok"] is True
    assert confounded_res.get("skipped_confounded") is True
    assert confounded_res["installed"] == []


def test_cli_meta_report_populates_library_provenance(temp_workspace: Path, capsys: Any) -> None:
    import argparse

    from evolver.cli import _cmd_meta_report
    from evolver.gep.asset_store import append_event_jsonl, upsert_gene

    upsert_gene(
        {
            "type": "Gene",
            "id": "gene_prov_cli",
            "category": "repair",
            "signals_match": ["err_cli"],
            "summary": "Check schema headers",
            "strategy": ["def check_headers(cols): return list(cols) == ['id', 'amount']"],
            "validation": ["pytest -q"],
        }
    )
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "id": "evt_prov_1",
            "timestamp": "2026-10-26T00:00:00Z",
            "gene_id": "gene_prov_cli",
            "signals": ["err_cli"],
            "outcome": {"status": "success", "score": 1.0},
            "diff_snapshot": (
                "diff --git a/src/check.py b/src/check.py\n"
                "+def check_headers(cols): return list(cols) == ['id', 'amount']\n"
            ),
        }
    )
    rc = _cmd_meta_report(argparse.Namespace(limit=50, json=True))
    assert rc == 0
    captured = json.loads(capsys.readouterr().out)
    prov = captured["panel"]["library_provenance"]
    assert prov is not None
    assert prov["evaluated_events"] == 1
    assert prov["origins"]["direct_copy"] == 1


def test_behavioral_contrast_note_summarizes_cross_round_transitions(
    temp_workspace: Path,
) -> None:
    prev_body = {
        "run_id": "run_prev",
        "checks": [
            {"command": "pytest tests/test_1.py", "ok": False},
            {"command": "pytest tests/test_2.py", "ok": True},
        ],
        "diff": "diff --git a/a.py b/a.py\n+x = 1\n",
    }
    cur_body = {
        "run_id": "run_cur",
        "checks": [
            {"command": "pytest tests/test_1.py", "ok": True},
            {"command": "pytest tests/test_2.py", "ok": False},
        ],
        "diff": "diff --git a/a.py b/a.py\n+x = 2\n",
    }
    assert "- behavioral_contrast:" not in episode_record.render_episode_block(cur_body)
    note = episode_record.behavioral_contrast_note(cur_body, prev_body)
    assert note == (
        '- behavioral_contrast: newly_passed=["pytest tests/test_1.py"] '
        'regressed=["pytest tests/test_2.py"] non_delivering=False'
    )
    # Unchanged passing checks with non-empty diff produces empty note
    same_body = {
        "run_id": "run_same",
        "checks": [{"command": "pytest tests/test_2.py", "ok": True}],
        "diff": "diff --git a/a.py b/a.py\n+x = 3\n",
    }
    assert episode_record.behavioral_contrast_note(same_body, same_body) == ""


def test_solidify_accepts_multi_candidate_proposal_and_short_circuits_keep_base(
    temp_workspace: Path,
) -> None:
    from evolver.gep.solidify import solidify, write_state_for_solidify

    write_state_for_solidify(
        {
            "run_id": "run_solidify_comp",
            "selected_gene_id": "gene_comp",
            "signals": ["err_comp"],
            "mutation": {"id": "mut_comp", "category": "repair", "validation": []},
        }
    )
    res = solidify(
        proposal={
            "gene_id": "gene_comp",
            "candidates": [
                {
                    "candidate_id": "c_hurt",
                    "role": "DOM",
                    "verdict": "hurt",
                    "proposal": {
                        "action": "patch",
                        "edits": [
                            {
                                "op": "append",
                                "file": "src/a.py",
                                "content": "x = 1\n",
                            }
                        ],
                    },
                }
            ],
        }
    )
    assert res["ok"] is True
    assert res["action"] == "no_action"
    assert res["proposal"]["decision"] == "keep_base"


def test_cli_variants_and_distill_strict_transferable(temp_workspace: Path, capsys: Any) -> None:
    import argparse

    from evolver.cli import _cmd_distill, _cmd_variants
    from evolver.gep.asset_store import append_event_jsonl
    from evolver.gep.variant_archive import record_variant

    record_variant(
        {
            "id": "evt_v1",
            "run_id": "run_v1",
            "gene_id": "gene_v1",
            "signals": ["sig_salvage"],
            "diff_snapshot": "diff --git a/scripts/fix.py b/scripts/fix.py\n+x = 1\n",
            "outcome": {"status": "failed", "error": "missing_rule"},
        },
        "semantic",
    )
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "id": "evt_later_v",
            "timestamp": "2026-10-26T00:00:00Z",
            "gene_id": "gene_v1",
            "signals": ["sig_salvage"],
            "outcome": {"status": "failed", "error": "different_error"},
        }
    )
    rc_v = _cmd_variants(
        argparse.Namespace(action=None, variant_id=None, signals="sig_salvage", json=True)
    )
    assert rc_v == 0
    v_out = json.loads(capsys.readouterr().out)
    assert v_out["salvageable_semantic"] == 1

    resp_file = temp_workspace / "resp_leaky.md"
    resp_file.write_text(
        "```json\n"
        + json.dumps(
            {
                "type": "Gene",
                "id": "gene_cli_leaky",
                "category": "repair",
                "signals_match": ["err"],
                "strategy": ["In this workspace edit src/a.py line 42"],
                "validation": ["pytest -q"],
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )
    rc_d = _cmd_distill(
        argparse.Namespace(
            response_file=str(resp_file),
            dry_run=False,
            strict_transferable=True,
        )
    )
    assert rc_d == 0
    d_out = capsys.readouterr().out
    assert "SKIPPED Gene gene_cli_leaky: workspace_fact_leakage" in d_out
