"""U-11: Migrate legacy in-repo and soak runtime state into ~/.evolver/workspaces/<id>/."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evolver.gep.paths import (
    compute_workspace_id,
    ensure_workspace_meta,
    get_repo_root,
    get_workspace_root,
    get_workspace_state_dir,
)
from evolver.ops.soak_env import soak_root


def _copy_tree_non_destructive(
    src_dir: Path,
    dest_dir: Path,
    *,
    dry_run: bool,
    migrated: list[str],
    skipped: list[str],
) -> int:
    if not src_dir.is_dir():
        return 0
    try:
        if src_dir.resolve() == dest_dir.resolve():
            return 0
    except OSError:
        pass

    count = 0
    for item in sorted(src_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src_dir)
        target = dest_dir / rel
        if target.is_file():
            try:
                if target.stat().st_mtime >= item.stat().st_mtime:
                    skipped.append(str(target))
                    continue
            except OSError:
                skipped.append(str(target))
                continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        migrated.append(str(target))
        count += 1
    return count


def migrate_workspace_state(
    repo_root: Path | str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy legacy ``memory/``, ``.evolver/gep/``, and ``soak/`` to external state root."""
    if repo_root is not None:
        target_repo = Path(repo_root).expanduser().resolve()
    else:
        found = get_repo_root(_quiet=True)
        target_repo = found.resolve() if found is not None else get_workspace_root().resolve()

    ws_id = compute_workspace_id(target_repo)
    state_root = get_workspace_state_dir(target_repo).resolve()
    if not dry_run:
        ensure_workspace_meta(target_repo)

    legacy_evo = target_repo / "memory" / "evolution"
    legacy_mem = target_repo / "memory"
    legacy_gep = target_repo / ".evolver" / "gep"
    legacy_soak = soak_root()

    migrated: list[str] = []
    skipped: list[str] = []
    sources_found: dict[str, str] = {}

    if legacy_evo.is_dir() and legacy_evo.resolve() != (state_root / "evolution").resolve():
        sources_found["in_repo_evolution"] = str(legacy_evo)
        _copy_tree_non_destructive(
            legacy_evo,
            state_root / "evolution",
            dry_run=dry_run,
            migrated=migrated,
            skipped=skipped,
        )

    if legacy_mem.is_dir() and legacy_mem.resolve() != state_root:
        for item in sorted(legacy_mem.iterdir()):
            if item.is_file():
                sources_found.setdefault("in_repo_memory_root", str(legacy_mem))
                dest_file = state_root / item.name
                if dest_file.is_file():
                    skipped.append(str(dest_file))
                else:
                    if not dry_run:
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_file)
                    migrated.append(str(dest_file))

    if legacy_gep.is_dir() and legacy_gep.resolve() != (state_root / "gep").resolve():
        sources_found["in_repo_gep"] = str(legacy_gep)
        _copy_tree_non_destructive(
            legacy_gep,
            state_root / "gep",
            dry_run=dry_run,
            migrated=migrated,
            skipped=skipped,
        )

    if legacy_soak.is_dir() and legacy_soak.resolve() != (state_root / "soak").resolve():
        soak_evo = legacy_soak / "evolution"
        if soak_evo.is_dir():
            sources_found["legacy_soak_evolution"] = str(soak_evo)
            _copy_tree_non_destructive(
                soak_evo,
                state_root / "soak" / "evolution",
                dry_run=dry_run,
                migrated=migrated,
                skipped=skipped,
            )
            _copy_tree_non_destructive(
                soak_evo,
                state_root / "evolution",
                dry_run=dry_run,
                migrated=migrated,
                skipped=skipped,
            )

    now_iso = datetime.now(UTC).isoformat()
    report_path = state_root / "migration_report.json"
    report: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "timestamp": now_iso,
        "repo_root": str(target_repo),
        "workspace_id": ws_id,
        "state_root": str(state_root),
        "sources_found": sources_found,
        "migrated_count": len(migrated),
        "skipped_count": len(skipped),
        "migrated_files": migrated,
        "skipped_existing": skipped,
        "report_path": str(report_path) if not dry_run else None,
    }
    if not dry_run:
        state_root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report


__all__ = ["migrate_workspace_state"]
