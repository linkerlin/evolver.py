"""Skills directory status for WebUI — with health monitor integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def skills_status(skills_dir: Path | None = None) -> dict[str, Any]:
    """Return status of the skills directory."""
    from evolver.gep.paths import get_skills_dir

    root = skills_dir or get_skills_dir()
    if not root.exists():
        return {"total": 0, "skills": []}

    skills: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if entry.is_dir() and (entry / "SKILL.md").exists():
            md = (entry / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
            skills.append(
                {
                    "id": entry.name,
                    "name": entry.name,
                    "has_skill_md": True,
                    "skill_md_length": len(md),
                }
            )

    return {"total": len(skills), "skills": skills}


def skills_health() -> dict[str, Any]:
    """Run skills health checks (from ops/skills_monitor)."""
    try:
        from evolver.ops.skills_monitor import check_skills_health

        return check_skills_health()
    except Exception:
        return {"healthy": False, "error": "skills health check failed"}


def skills_monitor_run() -> dict[str, Any]:
    """Run full skills monitor (dry-run by default)."""
    try:
        from evolver.ops.skills_monitor import run_skills_monitor

        return run_skills_monitor(dry_run=True)
    except Exception:
        return {"healthy": False, "error": "skills monitor failed"}
