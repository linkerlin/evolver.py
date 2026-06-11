"""Cursor IDE adapter.

Equivalent to ``evolver/src/adapters/cursor.js``.
Installs/uninstalls evolver hooks into ``.cursor/hooks.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from evolver.adapters.hook_adapter import (
    assert_safe_config_dir,
    copy_hook_scripts,
    merge_json_file,
    remove_evolver_hooks,
    remove_hook_scripts,
)

HOOK_SCRIPTS_DIR_NAME = "hooks"


def build_hooks_json(evolver_root: Path, is_user_level: bool) -> dict[str, Any]:
    scripts_base = "./hooks" if is_user_level else ".cursor/hooks"
    return {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {
                    "command": f"{sys.executable} -m evolver.adapters.scripts.session_start",
                    "timeout": 3,
                },
            ],
            "afterFileEdit": [
                {
                    "command": f"{sys.executable} -m evolver.adapters.scripts.signal_detect",
                    "matcher": "Write",
                    "timeout": 2,
                },
            ],
            "stop": [
                {
                    "command": f"{sys.executable} -m evolver.adapters.scripts.session_end",
                    "timeout": 8,
                    "loop_limit": 1,
                },
            ],
        },
    }


def install(*, config_root: Path, evolver_root: Path, force: bool = False) -> dict[str, Any]:
    is_user_level = config_root == Path.home()
    cursor_dir = config_root / ".cursor"
    hooks_json_path = cursor_dir / "hooks.json"
    hooks_dir = cursor_dir / HOOK_SCRIPTS_DIR_NAME
    assert_safe_config_dir(cursor_dir, ".cursor", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    if not force and hooks_json_path.exists():
        try:
            existing = json.loads(hooks_json_path.read_text(encoding="utf-8"))
            if existing.get("_evolver_managed"):
                print("[cursor] Evolver hooks already installed. Use --force to overwrite.")
                return {"ok": True, "skipped": True}
        except (json.JSONDecodeError, OSError):
            pass

    cursor_dir.mkdir(parents=True, exist_ok=True)

    hooks_cfg = build_hooks_json(evolver_root, is_user_level)
    merge_json_file(hooks_json_path, hooks_cfg)
    print(f"[cursor] Wrote {hooks_json_path}")

    copied = copy_hook_scripts(hooks_dir, evolver_root)
    print(f"[cursor] Copied {len(copied)} hook scripts to {hooks_dir}")
    print("[cursor] Installation complete.")
    print("[cursor] Restart Cursor or open a new session to activate hooks.")

    return {"ok": True, "platform": "cursor", "files": [str(hooks_json_path)] + [str(c) for c in copied]}


def uninstall(*, config_root: Path, evolver_root: Path) -> dict[str, Any]:
    cursor_dir = config_root / ".cursor"
    hooks_json_path = cursor_dir / "hooks.json"
    hooks_dir = cursor_dir / HOOK_SCRIPTS_DIR_NAME
    assert_safe_config_dir(cursor_dir, ".cursor", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    removed = remove_evolver_hooks(hooks_json_path)
    scripts = remove_hook_scripts(hooks_dir)

    if removed or scripts > 0:
        print(f"[cursor] Uninstalled evolver hooks ({scripts} scripts removed).")
    else:
        print("[cursor] No evolver hooks found to uninstall.")

    return {"ok": True, "removed": removed or scripts > 0}
