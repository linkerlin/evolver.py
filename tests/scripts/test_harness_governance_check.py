"""Harness/evaluator governance PR gate tests.

Port of ``evolver/test/harnessGovernanceCheck.test.js`` (v1.93.0).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "harness_governance_check.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("harness_governance_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["harness_governance_check"] = mod
    spec.loader.exec_module(mod)
    return mod


hg = _load_module()

BASE_PACKET = """
## Harness/evaluator governance

Upstream governance surface: PR metadata guard for Evolver harness/evaluator surfaces
Downstream EvoX impact: requires downstream PRs to keep EvoX bridge contracts aligned
Rollout-local scope: PR-time CI only
Promotion boundary: merge through reviewed PR only
Evaluator mismatch sets: observation/action/repair/verification/evidence/belief N/A for CI guard
Non-regression evidence: node --test test/harnessGovernanceCheck.test.js
Fix-severity review: low
Owner approval: repo owner via CODEOWNERS
Security boundary: no data/tool/host/network/secrets change
Rollback: revert this PR
Live promotion: no
Autonomous evaluator self-editing: no
"""


def test_does_not_trigger_for_unrelated_docs() -> None:
    assert hg.changed_files_touch_governance_surface(["docs/release-workflow.md"]) is False
    assert hg.validate_governance_packet("", ["docs/release-workflow.md"]) == []


def test_triggers_on_upstream_harness_surfaces() -> None:
    assert hg.changed_files_touch_governance_surface(["src/gep/selector.js"]) is True
    assert hg.changed_files_touch_governance_surface(["src/gep/a2aProtocol.js"]) is True
    assert hg.changed_files_touch_governance_surface(["src/gep/validator/report.js"]) is True
    assert hg.changed_files_touch_governance_surface(["src/evolve/pipeline/select.js"]) is True
    assert hg.changed_files_touch_governance_surface(["src/proxy/router/model_router.js"]) is True
    assert hg.changed_files_touch_governance_surface(["assets/gep/genes.json"]) is True


def test_triggers_on_python_repo_paths() -> None:
    assert hg.changed_files_touch_governance_surface(["src/evolver/gep/selector.py"]) is True
    assert (
        hg.changed_files_touch_governance_surface(["src/evolver/proxy/router/messages_route.py"])
        is True
    )
    assert (
        hg.changed_files_touch_governance_surface(["scripts/harness_governance_check.py"]) is True
    )


def test_requires_governance_packet_for_sensitive_changes() -> None:
    errors = hg.validate_governance_packet("## Summary\nchange selector", ["src/gep/selector.js"])
    assert len(errors) >= 8
    assert any("Live promotion" in e for e in errors)
    assert any("Autonomous evaluator self-editing" in e for e in errors)


def test_rejects_template_placeholders() -> None:
    placeholder_packet = """
## Harness/evaluator governance

Upstream governance surface: <typed Evolver surface, or N/A>
Downstream EvoX impact: <bridge/contract/runtime impact, or N/A>
Rollout-local scope: <proposal/shadow/cohort boundary before promotion, or N/A>
Promotion boundary: <proposal→rollout→PR/default boundary, or N/A>
Evaluator mismatch sets: <observation/action/repair/verification/evidence/belief sets covered, or N/A>
Non-regression evidence: <tests/shadow runs/replay/doc-only rationale, or N/A>
Fix-severity review: low
Owner approval: <owning module/reviewer requirement, or N/A>
Security boundary: <data/tool/host/network/secrets impact, or N/A>
Rollback: <disable/revert/quarantine path, or N/A>
Live promotion: no
Autonomous evaluator self-editing: no
"""
    errors = hg.validate_governance_packet(placeholder_packet, ["src/gep/a2aProtocol.js"])
    assert any("Upstream governance surface" in e for e in errors)
    assert any("Downstream EvoX impact" in e for e in errors)


def test_rejects_bare_na_template_evidence() -> None:
    bare_na_packet = """
## Harness/evaluator governance

Upstream governance surface: N/A -- not a harness/evaluator governance change
Downstream EvoX impact: N/A
Rollout-local scope: N/A:
Promotion boundary: N/A.
Evaluator mismatch sets: N/A
Non-regression evidence: N/A
Fix-severity review: low
Owner approval: N/A
Security boundary: N/A
Rollback: N/A
Live promotion: no
Autonomous evaluator self-editing: no
"""
    errors = hg.validate_governance_packet(bare_na_packet, ["src/gep/a2aProtocol.js"])
    assert any("Upstream governance surface" in e for e in errors)
    assert any("Rollback" in e for e in errors)


def test_accepts_complete_packet() -> None:
    errors = hg.validate_governance_packet(
        "## Summary\nchange gate\n" + BASE_PACKET, ["src/gep/selector.js"]
    )
    assert errors == []


def test_requires_exact_hard_no_values() -> None:
    soft_no = BASE_PACKET.replace(
        "Live promotion: no", "Live promotion: no, but later yes"
    ).replace(
        "Autonomous evaluator self-editing: no",
        "Autonomous evaluator self-editing: no way",
    )
    errors = hg.validate_governance_packet(soft_no, ["src/gep/selector.js"])
    assert any("Live promotion" in e for e in errors)
    assert any("Autonomous evaluator self-editing" in e for e in errors)


def test_strips_html_comments_before_validation() -> None:
    text = (
        "<!--\n## Harness/evaluator governance\n"
        "Live promotion: no\nAutonomous evaluator self-editing: no\n-->"
    )
    assert hg.strip_html_comments(text).strip() == ""
    errors = hg.validate_governance_packet(text, ["src/gep/selector.js"])
    assert len(errors) > 0


def test_main_passes_for_complete_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = tmp_path / "body.md"
    changed = tmp_path / "changed.txt"
    body.write_text("## Summary\n\n" + BASE_PACKET, encoding="utf-8")
    changed.write_text("src/gep/selector.js\n", encoding="utf-8")
    code = hg.main(["--body", str(body), "--changed", str(changed)])
    assert code == 0
    assert "PASSED" in capsys.readouterr().out


def test_main_fails_without_packet(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    changed = tmp_path / "changed.txt"
    body.write_text("## Summary\nno gate\n", encoding="utf-8")
    changed.write_text("src/evolver/gep/selector.py\n", encoding="utf-8")
    code = hg.main(["--body", str(body), "--changed", str(changed)])
    assert code == 1


def test_main_not_applicable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = tmp_path / "body.md"
    changed = tmp_path / "changed.txt"
    body.write_text("docs only\n", encoding="utf-8")
    changed.write_text("docs/readme.md\n", encoding="utf-8")
    code = hg.main(["--body", str(body), "--changed", str(changed)])
    assert code == 0
    assert "not applicable" in capsys.readouterr().out


def test_is_substantive_value_helpers() -> None:
    assert hg.is_substantive_value("real evidence") is True
    assert hg.is_substantive_value("<placeholder>") is False
    assert hg.is_substantive_value("N/A") is False
    assert hg.is_substantive_value("N/A -- note") is False
    assert hg.is_substantive_value("") is False
    assert hg.is_substantive_value(None) is False
