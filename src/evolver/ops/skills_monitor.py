"""Skills health monitor: detect and auto-fix common skill directory issues.

Equivalent to evolver/src/ops/skillsMonitor.js.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_repo_root

SKILL_DIR_CANDIDATES = ["skills", "skill", "src/skills", "agents/skills"]
SKILL_MD_TEMPLATE = """# {name}

## Description

Auto-generated skill stub.

## Usage

TBD

## Tags

- auto-generated
"""


def _find_skill_dirs(repo: Path) -> list[Path]:
    dirs: list[Path] = []
    for candidate in SKILL_DIR_CANDIDATES:
        p = repo / candidate
        if p.is_dir():
            dirs.append(p)
    return dirs


def _is_node_skill(skill_dir: Path) -> bool:
    return (skill_dir / "package.json").exists() or (skill_dir / "index.js").exists()


def _is_python_skill(skill_dir: Path) -> bool:
    return (skill_dir / "pyproject.toml").exists() or (skill_dir / "setup.py").exists()


def _check_skill_md(skill_dir: Path) -> tuple[bool, str]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return False, "missing"
    content = skill_md.read_text(encoding="utf-8", errors="replace")
    if len(content.strip()) < 50:
        return False, "too_short"
    if "## Description" not in content:
        return False, "missing_description"
    return True, "ok"


def _check_node_modules(skill_dir: Path) -> tuple[bool, str]:
    pkg = skill_dir / "package.json"
    if not pkg.exists():
        return True, "no_package_json"
    node_modules = skill_dir / "node_modules"
    if not node_modules.exists():
        return False, "missing_node_modules"
    return True, "ok"


def _check_venv(skill_dir: Path) -> tuple[bool, str]:
    pyproject = skill_dir / "pyproject.toml"
    if not pyproject.exists():
        return True, "no_pyproject"
    venv = skill_dir / ".venv"
    if not venv.exists():
        return False, "missing_venv"
    return True, "ok"


def _npm_install(skill_dir: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(skill_dir),
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _uv_sync(skill_dir: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=str(skill_dir),
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _create_skill_md(skill_dir: Path) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    name = skill_dir.name
    content = SKILL_MD_TEMPLATE.format(name=name)
    try:
        skill_md.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(skill_md)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_skills_health() -> dict[str, Any]:
    """Scan skill directories and report health status."""
    repo = get_repo_root()
    if not repo:
        return {"ok": False, "error": "no_repo_root", "skills": []}

    skill_dirs = _find_skill_dirs(repo)
    results: list[dict[str, Any]] = []

    for skill_dir in skill_dirs:
        # Recurse into subdirectories that look like individual skills
        subdirs = [d for d in skill_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if not subdirs:
            subdirs = [skill_dir]

        for sd in subdirs:
            md_ok, md_status = _check_skill_md(sd)
            result: dict[str, Any] = {
                "dir": sd.relative_to(repo).as_posix(),
                "type": None,
                "skill_md": {"ok": md_ok, "status": md_status},
                "node_modules": {"ok": True, "status": "n/a"},
                "venv": {"ok": True, "status": "n/a"},
            }

            if _is_node_skill(sd):
                result["type"] = "node"
                nm_ok, nm_status = _check_node_modules(sd)
                result["node_modules"] = {"ok": nm_ok, "status": nm_status}
            elif _is_python_skill(sd):
                result["type"] = "python"
                venv_ok, venv_status = _check_venv(sd)
                result["venv"] = {"ok": venv_ok, "status": venv_status}

            results.append(result)

    issues = [
        r
        for r in results
        if not r["skill_md"]["ok"] or not r["node_modules"]["ok"] or not r["venv"]["ok"]
    ]
    return {
        "ok": len(issues) == 0,
        "total_skills": len(results),
        "issues": len(issues),
        "skills": results,
    }


def auto_fix_skills(dry_run: bool = False) -> dict[str, Any]:
    """Auto-fix common skill issues.

    Returns a report of what was fixed (or would be fixed in dry-run mode).
    """
    health = check_skills_health()
    fixes: list[dict[str, Any]] = []

    for skill in health.get("skills", []):
        sd = get_repo_root() / skill["dir"]

        if not skill["skill_md"]["ok"]:
            if not dry_run:
                result = _create_skill_md(sd)
                fixes.append({"dir": skill["dir"], "action": "create_skill_md", **result})
            else:
                fixes.append(
                    {"dir": skill["dir"], "action": "create_skill_md", "ok": True, "dry_run": True}
                )

        if skill.get("type") == "node" and not skill["node_modules"]["ok"]:
            if not dry_run:
                result = _npm_install(sd)
                fixes.append({"dir": skill["dir"], "action": "npm_install", **result})
            else:
                fixes.append(
                    {"dir": skill["dir"], "action": "npm_install", "ok": True, "dry_run": True}
                )

        if skill.get("type") == "python" and not skill["venv"]["ok"]:
            if not dry_run:
                result = _uv_sync(sd)
                fixes.append({"dir": skill["dir"], "action": "uv_sync", **result})
            else:
                fixes.append(
                    {"dir": skill["dir"], "action": "uv_sync", "ok": True, "dry_run": True}
                )

    return {
        "ok": all(f.get("ok") for f in fixes),
        "fixes": fixes,
        "dry_run": dry_run,
    }


def run_skills_monitor(*, dry_run: bool = False) -> dict[str, Any]:
    """Entry point for the ops skills monitor.

    Checks skill health and optionally auto-fixes issues.
    Records events to the evolution log.
    """
    health = check_skills_health()
    if health.get("issues", 0) > 0:
        fix_result = auto_fix_skills(dry_run=dry_run)
        return {
            "ok": fix_result["ok"],
            "health": health,
            "fixes": fix_result["fixes"],
            "dry_run": dry_run,
        }
    return {"ok": True, "health": health, "fixes": [], "dry_run": dry_run}


__all__ = ["auto_fix_skills", "check_skills_health", "run_skills_monitor"]
