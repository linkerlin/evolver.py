"""Tests for evolver.bench.cost (经验即证据 §5.7 — 采集先行)."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.bench import cost


def _receipt(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "evolver.solve_receipt.v0",
                "task": "t1",
                "cost": None,
                "model": None,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_unmeasured_by_default(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "r.json")
    assert cost.read_cost(receipt) == {"status": "unmeasured"}


def test_record_cost_fills_tokens_and_model(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "r.json")
    cost.record_cost(receipt, input_tokens=100, output_tokens=50, model="deepseek-v4-flash")
    result = cost.read_cost(receipt)
    assert result["status"] == "measured"
    assert result["cost"]["input_tokens"] == 100
    assert result["cost"]["output_tokens"] == 50
    assert result["cost"]["total_tokens"] == 150
    assert result["model"] == "deepseek-v4-flash"


def test_record_cost_without_model_still_measured(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "r.json")
    cost.record_cost(receipt, input_tokens=10, output_tokens=5)
    result = cost.read_cost(receipt)
    assert result["status"] == "measured"
    assert result["model"] is None


def test_read_cost_missing_receipt_is_unmeasured(tmp_path: Path) -> None:
    assert cost.read_cost(tmp_path / "nope.json") == {
        "status": "unmeasured",
        "reason": "no_receipt",
    }


def test_record_cost_preserves_provenance(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "r.json")
    cost.record_cost(receipt, input_tokens=1, output_tokens=1)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["format"] == "evolver.solve_receipt.v0"
    assert data["task"] == "t1"
