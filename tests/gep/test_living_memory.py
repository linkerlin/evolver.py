"""Tests for evolver.gep.living_memory."""

from __future__ import annotations

from evolver.gep.living_memory import (
    clear_living_memory_cache,
    format_guard_items,
    format_risk_warnings,
    load_living_memory,
    parse_yaml_frontmatter,
)


def test_parse_yaml_frontmatter():
    content = """---
autopoiesis: true
evolution_count: 2
friction_points:
  - id: "f001"
    category: "runtime"
    description: "import error"
    resolution: "fix import"
    timestamp: "2026-06-08T10:00:00"
---
# body
"""
    fm = parse_yaml_frontmatter(content)
    assert fm is not None
    assert fm["evolution_count"] == "2"
    assert len(fm["friction_points"]) == 1
    assert fm["friction_points"][0]["id"] == "f001"


def test_load_living_memory(temp_workspace):
    clear_living_memory_cache()
    lessons = temp_workspace / "memory" / "evolution" / "LESSONS_LEARNED.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text(
        """---
autopoiesis: true
evolution_count: 1
friction_points:
  - id: "f001"
    category: "hub_offline"
    description: "hub unreachable"
    resolution: "retry later"
    timestamp: "2026-06-08T10:00:00"
---
# Lessons
""",
        encoding="utf-8",
    )
    memory = load_living_memory(lessons)
    assert memory["loaded"] is True
    assert memory["total_friction_points"] == 1
    assert "hub_offline" in memory["all_categories"]
    warnings = format_risk_warnings(memory)
    assert "hub_offline" in warnings
    items = format_guard_items(memory)
    assert items[0]["source"] == "living_memory"
