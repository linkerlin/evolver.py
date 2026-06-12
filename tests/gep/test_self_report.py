"""Tests for evolver.gep.self_report."""

from __future__ import annotations

import json

from evolver.gep.self_report import SelfReport


def test_self_report_no_write_preserves_governance_files(temp_workspace, monkeypatch):
    """Port of md2video test_self_report_no_write_preserves_governance_files."""
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    evolution = temp_workspace / "memory" / "evolution"
    evolution.mkdir(parents=True, exist_ok=True)

    rules_path = gep / "autopoiesis_rules.json"
    lessons_path = evolution / "LESSONS_LEARNED.md"
    rules_before = {
        "version": "test",
        "guard_checks": {},
        "autopoiesis": {"self_report_enabled": True, "evolution_count": 0},
    }
    lessons_before = """---
autopoiesis: true
memory_type: "living"
last_updated: "2026-06-08"
evolution_count: 0
friction_points:
---

# LESSONS
"""
    rules_path.write_text(json.dumps(rules_before, ensure_ascii=False, indent=2), encoding="utf-8")
    lessons_path.write_text(lessons_before, encoding="utf-8")

    report = SelfReport()
    report.capture_friction("test", "no-write should not persist", "keep files unchanged")
    report_path, data = report.run(no_write=True, print_human=False)

    assert report_path is None
    assert json.loads(rules_path.read_text(encoding="utf-8")) == rules_before
    assert lessons_path.read_text(encoding="utf-8") == lessons_before
    assert not (evolution / "self_report.json").exists()
    assert data["friction_summary"]["total"] == 1


def test_self_report_auto_encode_writes_rules(temp_workspace):
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (temp_workspace / "memory" / "evolution").mkdir(parents=True, exist_ok=True)

    report = SelfReport()
    report.capture_friction("runtime", "traceback in session", "run pytest")
    report.run(no_write=False, print_human=False)

    rules = json.loads((gep / "autopoiesis_rules.json").read_text(encoding="utf-8"))
    assert "runtime_guard" in rules["guard_checks"]
    assert rules["guard_checks"]["runtime_guard"]["autopoiesis"] is True
    pending = json.loads((gep / "pending_signals.json").read_text(encoding="utf-8"))
    assert "autopoiesis:runtime_guard" in pending["signals"]
