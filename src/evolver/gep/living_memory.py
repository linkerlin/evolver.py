"""Living memory loader — runtime friction awareness from LESSONS_LEARNED.md.

Ported from md2video ``harness/memory_loader.py``. Loads YAML frontmatter friction
points with mtime caching and formats risk warnings for the evolution pipeline.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolution_dir

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _match_kv(text: str) -> tuple[str, str] | None:
    match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$", text)
    if match:
        return match.group(1), match.group(2).strip()
    return None


def parse_yaml_frontmatter(content: str) -> dict[str, Any] | None:
    """Lightweight YAML frontmatter parser for LESSONS_LEARNED.md."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    end_idx = -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_idx = index
            break
    if end_idx == -1:
        return None

    yaml_lines = lines[1:end_idx]
    result: dict[str, Any] = {"friction_points": []}
    index = 0
    while index < len(yaml_lines):
        line = yaml_lines[index]
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            index += 1
            continue

        if trimmed.startswith("- "):
            after_dash = trimmed[2:].strip()
            kv_match = _match_kv(after_dash)
            if kv_match:
                key, val = kv_match
                obj: dict[str, Any] = {key: _strip_quotes(val)}
                index += 1
                while index < len(yaml_lines):
                    next_line = yaml_lines[index]
                    next_trimmed = next_line.strip()
                    if next_trimmed.startswith("- ") or next_trimmed == "---":
                        break
                    if not next_trimmed:
                        if (
                            index + 1 < len(yaml_lines)
                            and yaml_lines[index + 1].strip().startswith("- ")
                        ):
                            index += 1
                            break
                        index += 1
                        continue
                    next_kv = _match_kv(next_trimmed)
                    if next_kv:
                        obj[next_kv[0]] = _strip_quotes(next_kv[1])
                    index += 1
                result["friction_points"].append(obj)
                continue
            index += 1
            continue

        top_kv = _match_kv(trimmed)
        if top_kv and top_kv[0] != "friction_points":
            result[top_kv[0]] = _strip_quotes(top_kv[1])
        index += 1

    return result


def default_lessons_path() -> Path:
    return get_evolution_dir() / "LESSONS_LEARNED.md"


def load_living_memory(lessons_path: Path | str | None = None) -> dict[str, Any]:
    """Load living memory with mtime cache."""
    global _cache, _cache_mtime

    path = Path(lessons_path) if lessons_path else default_lessons_path()
    if not path.exists():
        return {"loaded": False, "reason": "file_not_found", "friction_points": []}

    try:
        stat = path.stat()
        if _cache is not None and _cache_mtime == stat.st_mtime:
            return _cache

        content = path.read_text(encoding="utf-8")
        frontmatter = parse_yaml_frontmatter(content)
        if frontmatter is None:
            return {"loaded": False, "reason": "no_yaml_frontmatter", "friction_points": []}

        valid_fps = [
            fp
            for fp in frontmatter.get("friction_points", [])
            if isinstance(fp, dict)
            and fp.get("description")
            and str(fp.get("description")).strip()
            and str(fp.get("description")).strip().lower() != "undefined"
        ]

        def _ts_key(fp: dict[str, Any]) -> float:
            ts = str(fp.get("timestamp", ""))
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0

        sorted_fps = sorted(valid_fps, key=_ts_key, reverse=True)
        recent = sorted_fps[:5]
        cat_counts = Counter(fp.get("category", "uncategorized") for fp in valid_fps)
        high_cats = [cat for cat, _ in cat_counts.most_common(3)]
        high_friction = [fp for fp in sorted_fps if fp.get("category") in high_cats][:3]

        result = {
            "loaded": True,
            "evolution_count": frontmatter.get("evolution_count", len(valid_fps)),
            "last_updated": frontmatter.get("last_updated", ""),
            "total_friction_points": len(valid_fps),
            "recent_friction_points": recent,
            "high_friction_points": high_friction,
            "all_categories": sorted(
                {fp.get("category", "uncategorized") for fp in valid_fps if fp.get("category")}
            ),
            "friction_points": valid_fps,
        }
        _cache = result
        _cache_mtime = stat.st_mtime
        return result
    except OSError as exc:
        return {"loaded": False, "reason": str(exc), "friction_points": []}


def clear_living_memory_cache() -> None:
    """Reset module cache (for tests)."""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None


def format_risk_warnings(memory: dict[str, Any]) -> str:
    """Human-readable risk warnings for console / prompt context."""
    if not memory.get("loaded") or not memory.get("high_friction_points"):
        return ""

    lines = [
        "",
        "━━━ Living memory risk warnings ━━━",
        (
            f"Loaded {memory['total_friction_points']} historical friction points; "
            f"top categories: {', '.join(memory['all_categories'][:3]) or 'none'}"
        ),
        "",
    ]
    for fp in memory["high_friction_points"]:
        desc = str(fp.get("description", ""))[:80]
        resolution = str(fp.get("resolution", ""))
        lines.append(f"  [{fp.get('id', '?')}] {fp.get('category', 'uncategorized')}: {desc}")
        if resolution:
            lines.append(f"     -> {resolution[:80]}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_guard_items(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Guard checklist items derived from recent friction points."""
    if not memory.get("loaded") or not memory.get("recent_friction_points"):
        return []

    items: list[dict[str, Any]] = []
    for fp in memory["recent_friction_points"]:
        desc = str(fp.get("description", ""))
        resolution = str(fp.get("resolution", ""))
        message = f"[living_memory] {desc}"
        if resolution:
            message += f" -> {resolution}"
        items.append(
            {
                "level": "guard",
                "id": f"memory_{fp.get('id', '?')}",
                "message": message,
                "source": "living_memory",
                "friction_id": fp.get("id"),
                "category": fp.get("category"),
                "auto_detect": False,
            }
        )
    return items
