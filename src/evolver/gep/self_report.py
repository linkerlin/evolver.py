"""Self Report — Autopoiesis self-inspection and rule evolution for GEP.

Ported from md2video ``harness/self_report.py``. Observes GEP state, captures
pipeline friction, encodes guard rules into ``autopoiesis_rules.json``, and
maintains ``LESSONS_LEARNED.md`` as the living memory organ.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evolver.gep.asset_store import append_pending_signals, read_json_if_exists
from evolver.gep.living_memory import clear_living_memory_cache, parse_yaml_frontmatter
from evolver.gep.paths import get_evolution_dir, get_gep_assets_dir, get_solidify_state_path

logger = logging.getLogger(__name__)

_CATEGORY_RULE_MAP: dict[str, str] = {
    "session_error": "session_error_guard",
    "repair_loop": "repair_loop_guard",
    "hub_offline": "hub_offline_guard",
    "hub_quality": "hub_quality_guard",
    "environment": "environment_guard",
    "runtime": "runtime_guard",
    "dependency": "dependency_guard",
    "solidify": "solidify_guard",
}


@dataclass
class FrictionPoint:
    id: str
    category: str
    description: str
    resolution: str = ""
    rule_id: str | None = None
    auto_encode: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SelfReport:
    """Autopoiesis self-report engine for evolver.py."""

    def __init__(self) -> None:
        self.evolution_dir = get_evolution_dir()
        self.rules_path = get_gep_assets_dir() / "autopoiesis_rules.json"
        self.lessons_path = self.evolution_dir / "LESSONS_LEARNED.md"
        self.solidify_path = get_solidify_state_path()

        self.friction_points: list[FrictionPoint] = []
        self.system_state: dict[str, Any] = {}
        self.rules: dict[str, Any] = {}
        self.report: dict[str, Any] = {}

    @staticmethod
    def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
        data = read_json_if_exists(path)
        return data if isinstance(data, dict) else (default or {})

    @staticmethod
    def _save_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_system_state(self) -> None:
        """Load current GEP / evolution state."""
        from evolver.gep.asset_store import load_capsules, load_genes, read_all_events

        genes = load_genes()
        capsules = load_capsules()
        events = read_all_events()
        solidify = self._load_json(self.solidify_path)
        raw_last_run = solidify.get("last_run")
        last_run: dict[str, Any] = raw_last_run if isinstance(raw_last_run, dict) else {}

        self.system_state = {
            "rules_version": self._load_json(self.rules_path).get("version", "unknown"),
            "evolution_dir_exists": self.evolution_dir.exists(),
            "living_memory_exists": self.lessons_path.exists(),
            "solidify_pending": bool(last_run) and not solidify.get("last_solidify"),
            "genes_count": len(genes),
            "capsules_count": len(capsules),
            "events_count": len(events),
            "last_run_id": last_run.get("run_id"),
        }
        self.rules = self._load_json(
            self.rules_path,
            {"version": "1.0.0", "guard_checks": {}, "autopoiesis": {}},
        )

    def capture_friction(
        self,
        category: str,
        description: str,
        resolution: str = "",
        *,
        rule_id: str | None = None,
        auto_encode: bool = True,
    ) -> FrictionPoint:
        fid = f"f{len(self.friction_points) + 1:03d}"
        fp = FrictionPoint(
            id=fid,
            category=category,
            description=description,
            resolution=resolution,
            rule_id=rule_id,
            auto_encode=auto_encode,
        )
        self.friction_points.append(fp)
        return fp

    def _generate_rule_id(self, category: str) -> str:
        safe = category.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
        return _CATEGORY_RULE_MAP.get(category, f"auto_{safe}")

    def auto_encode(self, *, write: bool = True) -> int:
        """Encode friction points into autopoiesis_rules.json guard_checks."""
        if not self.rules:
            return 0

        guard_checks = self.rules.setdefault("guard_checks", {})
        if not isinstance(guard_checks, dict):
            guard_checks = {}
            self.rules["guard_checks"] = guard_checks

        new_rules_count = 0
        pending_signals: list[str] = []

        for fp in self.friction_points:
            if not fp.auto_encode:
                continue
            rule_id = fp.rule_id or self._generate_rule_id(fp.category)
            if rule_id not in guard_checks:
                guard_checks[rule_id] = {
                    "id": rule_id,
                    "name": f"[AUTO] {fp.category}",
                    "description": fp.description,
                    "auto_detect": True,
                    "origin_friction": fp.id,
                    "autopoiesis": True,
                    "signal_key": f"autopoiesis:{rule_id}",
                }
                new_rules_count += 1
                pending_signals.append(f"autopoiesis:{rule_id}")
            fp.rule_id = rule_id

        if new_rules_count > 0:
            apo_meta = self.rules.setdefault("autopoiesis", {})
            apo_meta.update(
                {
                    "self_report_enabled": True,
                    "auto_encode": True,
                    "last_evolution": datetime.now(UTC).isoformat(),
                    "evolution_count": int(apo_meta.get("evolution_count", 0)) + new_rules_count,
                }
            )
            if write:
                self._save_json(self.rules_path, self.rules)
                append_pending_signals(pending_signals)

        return new_rules_count

    def _load_lessons(self) -> dict[str, Any]:
        if not self.lessons_path.exists():
            return {"frontmatter": {}, "body": ""}
        content = self.lessons_path.read_text(encoding="utf-8")
        frontmatter = parse_yaml_frontmatter(content) or {}
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()
        return {"frontmatter": frontmatter, "body": body}

    def write_lessons(self) -> None:
        """Update LESSONS_LEARNED.md living memory organ."""
        lessons = self._load_lessons()
        fm = dict(lessons.get("frontmatter", {}))

        fm["autopoiesis"] = True
        fm["memory_type"] = "living"
        fm["last_updated"] = datetime.now(UTC).strftime("%Y-%m-%d")
        fm["evolution_count"] = int(fm.get("evolution_count", 0)) + len(self.friction_points)

        existing_fps = fm.get("friction_points", [])
        if not isinstance(existing_fps, list):
            existing_fps = []
        existing_ids = {f.get("id") for f in existing_fps if isinstance(f, dict)}

        for fp in self.friction_points:
            if fp.id not in existing_ids:
                existing_fps.append(
                    {
                        "id": fp.id,
                        "category": fp.category,
                        "description": fp.description,
                        "resolution": fp.resolution,
                        "rule_id": fp.rule_id,
                        "timestamp": fp.timestamp,
                    }
                )
        fm["friction_points"] = existing_fps

        body_lines = [
            "# LESSONS_LEARNED — evolver.py living memory\n",
            (
                "> Maintained by ``evolver.gep.self_report``. Friction points link to "
                "``autopoiesis_rules.json`` via ``rule_id``.\n"
            ),
        ]
        by_category: dict[str, list[dict[str, Any]]] = {}
        for fp_data in existing_fps:
            if not isinstance(fp_data, dict):
                continue
            cat = str(fp_data.get("category", "uncategorized"))
            by_category.setdefault(cat, []).append(fp_data)

        for cat, fps in sorted(by_category.items()):
            body_lines.append(f"\n## Friction category: {cat}\n")
            for fp_data in fps:
                body_lines.append(f"\n### {fp_data['id']}\n")
                body_lines.append(f"- **description**: {fp_data['description']}\n")
                if fp_data.get("resolution"):
                    body_lines.append(f"- **resolution**: {fp_data['resolution']}\n")
                if fp_data.get("rule_id"):
                    body_lines.append(f"- **rule_id**: `{fp_data['rule_id']}`\n")
                body_lines.append(f"- **timestamp**: {fp_data.get('timestamp', 'unknown')}\n")

        body_lines.append(
            "\n---\n\n*Auto-maintained by evolver.gep.self_report. "
            "Add custom sections after the frontmatter block.*\n"
        )
        body = "".join(body_lines)

        fm_lines = ["---"]
        for key, value in fm.items():
            if key == "friction_points":
                fm_lines.append(f"{key}:")
                for fp_data in value:
                    if not isinstance(fp_data, dict):
                        continue
                    fm_lines.append(f'  - id: "{fp_data["id"]}"')
                    fm_lines.append(f'    category: "{fp_data["category"]}"')
                    desc = str(fp_data.get("description", "")).replace('"', '\\"')
                    fm_lines.append(f'    description: "{desc}"')
                    if fp_data.get("resolution"):
                        res = str(fp_data["resolution"]).replace('"', '\\"')
                        fm_lines.append(f'    resolution: "{res}"')
                    if fp_data.get("rule_id"):
                        fm_lines.append(f'    rule_id: "{fp_data["rule_id"]}"')
                    if fp_data.get("timestamp"):
                        fm_lines.append(f'    timestamp: "{fp_data["timestamp"]}"')
            elif isinstance(value, bool):
                fm_lines.append(f"{key}: {str(value).lower()}")
            elif isinstance(value, int):
                fm_lines.append(f"{key}: {value}")
            elif isinstance(value, str):
                fm_lines.append(f'{key}: "{value}"')
            else:
                fm_lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        fm_lines.append("---")

        self.lessons_path.parent.mkdir(parents=True, exist_ok=True)
        self.lessons_path.write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
        clear_living_memory_cache()

    def generate_report(self) -> dict[str, Any]:
        """Build machine-readable self-report payload."""
        by_category: dict[str, int] = {}
        for fp in self.friction_points:
            by_category[fp.category] = by_category.get(fp.category, 0) + 1

        recommendations: list[str] = []
        if not self.system_state.get("genes_count"):
            recommendations.append("No genes loaded — seed GEP assets or run sync")
        if self.system_state.get("solidify_pending"):
            recommendations.append("Solidify pending — run `evolver solidify`")
        if not self.system_state.get("living_memory_exists"):
            recommendations.append(
                "Living memory not initialized — friction will seed LESSONS_LEARNED.md"
            )

        apo_meta = self.rules.get("autopoiesis", {})
        self.report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "system_state": self.system_state,
            "friction_summary": {
                "total": len(self.friction_points),
                "by_category": by_category,
                "auto_encoded": sum(
                    1 for fp in self.friction_points if fp.auto_encode and fp.rule_id
                ),
            },
            "evolution": {
                "rules_version": self.rules.get("version", "unknown"),
                "autopoiesis_enabled": apo_meta.get("self_report_enabled", False),
                "evolution_count": apo_meta.get("evolution_count", 0),
                "new_rules_this_run": sum(1 for fp in self.friction_points if fp.auto_encode),
            },
            "recommendations": recommendations,
        }
        return self.report

    def save_report(self) -> Path:
        path = self.evolution_dir / "self_report.json"
        self._save_json(path, self.report)
        return path

    def run(
        self,
        *,
        no_write: bool = False,
        print_human: bool = False,
    ) -> tuple[Path | None, dict[str, Any]]:
        """Full self-report cycle: observe → encode → remember → report."""
        self.load_system_state()
        self.auto_encode(write=not no_write)
        if not no_write:
            self.write_lessons()
        self.generate_report()
        report_path = None if no_write else self.save_report()
        if print_human:
            logger.info(
                "[SelfReport] friction=%s evolution_count=%s",
                self.report["friction_summary"]["total"],
                self.report["evolution"].get("evolution_count"),
            )
        return report_path, self.report
