"""Tests for evolver.webui.observer.insights."""

from __future__ import annotations

import json

from evolver.webui.observer.insights import pipeline_insights


def test_empty_insights(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "evolver.webui.observer.insights.get_solidify_state_path",
        lambda: tmp_path / "solidify.json",
    )
    monkeypatch.setattr(
        "evolver.evolve.pipeline.collect.read_real_session_log",
        lambda: "clean log without issues",
    )
    result = pipeline_insights()
    assert "failure_diagnosis" in result
    assert result["failure_diagnosis"] is None
    assert result["hub_quality_gate"]["services"] == []


def test_last_run_diagnosis(monkeypatch, tmp_path):
    solidify = tmp_path / "solidify.json"
    monkeypatch.setattr(
        "evolver.webui.observer.insights.get_solidify_state_path",
        lambda: solidify,
    )
    solidify.write_text(
        json.dumps(
            {
                "last_run": {
                    "run_id": "r1",
                    "failure_diagnosis": {
                        "category": "environment",
                        "confidence": 0.9,
                        "cause": "missing pkg",
                        "recommendation": "pip install",
                        "relevant_lines": [],
                    },
                    "hub_quality_gate": {
                        "services": [
                            {
                                "service_id": "s1",
                                "review": {"verdict": "approve", "score": 95},
                            }
                        ],
                        "assets": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    result = pipeline_insights()
    assert result["failure_diagnosis"]["category"] == "environment"
    assert result["hub_quality_summary"]["service_reviews"] == 1


def test_last_run_autopoiesis(monkeypatch, tmp_path):
    solidify = tmp_path / "solidify.json"
    monkeypatch.setattr(
        "evolver.webui.observer.insights.get_solidify_state_path",
        lambda: solidify,
    )
    solidify.write_text(
        json.dumps(
            {
                "last_run": {
                    "run_id": "r2",
                    "autopoiesis": {
                        "self_report": {
                            "friction_summary": {"total": 2, "by_category": {"runtime": 2}},
                            "evolution": {"evolution_count": 4, "autopoiesis_enabled": True},
                        },
                        "living_memory": {"total_friction_points": 5, "evolution_count": 4},
                        "viability": {"score": 0.82, "status": "stable"},
                        "homeostasis": {"actions": ["maintain"], "status": "stable"},
                        "tick_id": "apo_1",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    result = pipeline_insights()
    assert result["autopoiesis"]["self_report"]["friction_summary"]["total"] == 2
    assert result["autopoiesis"]["viability"]["status"] == "stable"
    assert result["autopoiesis_source"] == "last_run"


def test_insights_preflight_abort(monkeypatch, tmp_path):
    solidify = tmp_path / "solidify.json"
    monkeypatch.setattr(
        "evolver.webui.observer.insights.get_solidify_state_path",
        lambda: solidify,
    )
    monkeypatch.setattr(
        "evolver.webui.observer.insights.read_preflight_abort_report",
        lambda: {
            "reason": "repair loop",
            "report": {"friction_summary": {"total": 1}},
        },
    )
    result = pipeline_insights()
    assert result["preflight_abort"]["reason"] == "repair loop"


def test_insights_memory_sync(monkeypatch, tmp_path):
    solidify = tmp_path / "solidify.json"
    monkeypatch.setattr(
        "evolver.webui.observer.insights.get_solidify_state_path",
        lambda: solidify,
    )
    solidify.write_text(
        json.dumps(
            {
                "last_run": {
                    "run_id": "r3",
                    "signals": ["error"],
                    "memory_advice": {
                        "frictionCategories": ["solidify"],
                        "bannedGeneIds": ["gene_bad"],
                        "livingMemoryHints": ["living_memory_risk:solidify"],
                    },
                    "memory_graph_friction_synced": {"synced": 1, "ids": ["fp1"]},
                },
            }
        ),
        encoding="utf-8",
    )
    result = pipeline_insights()
    ms = result["memory_sync"]
    assert ms["unified_hints_count"] == 1
    assert "solidify" in ms["friction_categories"]
    assert ms["last_run_friction_synced"]["synced"] == 1
