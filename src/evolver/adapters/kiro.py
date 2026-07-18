"""Kiro IDE adapter.

Equivalent to ``evolver/src/adapters/kiro.js``.
Installs/uninstalls evolver hooks into ``.kiro/hooks/*.kiro.hook``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.adapters.hook_adapter import (
    assert_safe_config_dir,
    copy_hook_scripts,
    remove_hook_scripts,
    remove_marked_section,
)

HOOK_SCRIPTS_DIR_NAME = "hooks"
EVOLVER_MARKER = "<!-- evolver-evolution-memory -->"
HOOK_FILE_SUFFIX = ".kiro.hook"
HOOK_FILES = {
    "session_start": "evolver-session-start.kiro.hook",
    "signal_detect": "evolver-signal-detect.kiro.hook",
    "session_end": "evolver-session-end.kiro.hook",
}


def build_hook_config(kind: str, scripts_base: str) -> dict[str, Any]:
    from evolver.uv_runtime import hook_command_string

    session_start_cmd = "EVOLVER_SESSION_START_DEDUP=1 " + hook_command_string(
        "evolver.adapters.scripts.session_start"
    )
    templates: dict[str, dict[str, Any]] = {
        "session_start": {
            "name": "Evolver Session Start",
            "version": "1",
            "description": (
                "Reads recent evolution memory from the local memory graph "
                "and injects it as context when a prompt is submitted."
            ),
            "when": {"type": "promptSubmit"},
            "then": {
                "type": "runCommand",
                "command": session_start_cmd,
                "timeout": 3,
            },
            "_evolver_managed": True,
        },
        "signal_detect": {
            "name": "Evolver Signal Detect",
            "version": "1",
            "description": (
                "Detects evolution signals (errors, perf bottlenecks, capability gaps, "
                "test failures) in file content after write operations."
            ),
            "when": {"type": "postToolUse", "toolTypes": ["write"]},
            "then": {
                "type": "runCommand",
                "command": hook_command_string("evolver.adapters.scripts.signal_detect"),
                "timeout": 2,
            },
            "_evolver_managed": True,
        },
        "session_end": {
            "name": "Evolver Session End",
            "version": "1",
            "description": (
                "Records evolution outcome at session end by analyzing git diff stats "
                "and writing to the local memory graph."
            ),
            "when": {"type": "agentStop"},
            "then": {
                "type": "runCommand",
                "command": hook_command_string("evolver.adapters.scripts.session_end"),
                "timeout": 8,
            },
            "_evolver_managed": True,
        },
    }
    return templates[kind]


def build_agents_md_section() -> str:
    return f"""{EVOLVER_MARKER}
## Evolution Memory (Evolver)

This project uses evolver for self-evolution. Hooks automatically:
1. Inject recent evolution memory on prompt submit
2. Detect evolution signals during file edits
3. Record outcomes at session end

For substantive tasks, call `gep_recall` before work and `gep_record_outcome` after.
Signals: log_error, perf_bottleneck, user_feature_request, capability_gap,
deployment_issue, test_failure."""


def _append_section_to_file(file_path: Path, marker: str, content: str) -> bool:
    existing = ""
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")
    if marker in existing:
        return False
    separator = "\n\n" if existing and not existing.endswith("\n") else "\n"
    file_path.write_text(existing + separator + content + "\n", encoding="utf-8")
    return True


def _write_hook_file(hooks_dir: Path, file_name: str, config: dict[str, Any]) -> Path:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest = hooks_dir / file_name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return dest


def _is_evolver_managed_hook_file(file_path: Path) -> bool:
    try:
        raw = file_path.read_text(encoding="utf-8").strip()
        if not raw:
            return False
        data = json.loads(raw)
        if data.get("_evolver_managed") is True:
            return True
        if isinstance(data.get("name"), str) and data["name"].lower().startswith("evolver"):
            return True
        then = data.get("then")
        if isinstance(then, dict) and isinstance(then.get("command"), str):
            if re.search(r"evolver-(session|signal)", then["command"]):
                return True
    except (json.JSONDecodeError, OSError):
        pass
    return False


def install(
    *,
    config_root: Path,
    evolver_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    kiro_dir = config_root / ".kiro"
    hooks_dir = kiro_dir / HOOK_SCRIPTS_DIR_NAME
    agents_md_path = config_root / "AGENTS.md"
    scripts_base = ".kiro/hooks"
    assert_safe_config_dir(kiro_dir, ".kiro", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    hook_paths = [hooks_dir / name for name in HOOK_FILES.values()]

    if not force:
        existing_evolver_hook = None
        for p in hook_paths:
            if p.exists() and _is_evolver_managed_hook_file(p):
                existing_evolver_hook = p
                break
        if existing_evolver_hook:
            print("[kiro] Evolver hooks already installed. Use --force to overwrite.")
            return {"ok": True, "skipped": True}

    hooks_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for kind, file_name in HOOK_FILES.items():
        cfg = build_hook_config(kind, scripts_base)
        dest = _write_hook_file(hooks_dir, file_name, cfg)
        written.append(dest)
        print(f"[kiro] Wrote {dest}")

    copied = copy_hook_scripts(hooks_dir, evolver_root)
    print(f"[kiro] Copied {len(copied)} hook scripts to {hooks_dir}")

    injected = _append_section_to_file(agents_md_path, EVOLVER_MARKER, build_agents_md_section())
    if injected:
        print(f"[kiro] Injected evolution section into {agents_md_path}")

    print("[kiro] Installation complete.")
    print("[kiro] Kiro auto-discovers *.kiro.hook files in .kiro/hooks/ -- no restart needed.")

    return {
        "ok": True,
        "platform": "kiro",
        "files": [str(w) for w in written] + [str(agents_md_path)] + [str(c) for c in copied],
    }


def uninstall(
    *,
    config_root: Path,
    evolver_root: Path,
) -> dict[str, Any]:
    kiro_dir = config_root / ".kiro"
    hooks_dir = kiro_dir / HOOK_SCRIPTS_DIR_NAME
    agents_md_path = config_root / "AGENTS.md"
    assert_safe_config_dir(kiro_dir, ".kiro", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    changed = False
    removed_count = 0

    if hooks_dir.exists():
        try:
            for entry in hooks_dir.iterdir():
                if not entry.name.endswith(HOOK_FILE_SUFFIX):
                    continue
                if _is_evolver_managed_hook_file(entry):
                    try:
                        entry.unlink()
                        removed_count += 1
                        changed = True
                    except OSError:
                        pass
        except OSError:
            pass

    scripts = remove_hook_scripts(hooks_dir)
    if scripts > 0:
        changed = True

    if remove_marked_section(agents_md_path, EVOLVER_MARKER):
        changed = True

    print(
        (
            f"[kiro] Uninstalled evolver hooks "
            f"({removed_count} hook files + {scripts} scripts removed)."
        )
        if changed
        else "[kiro] No evolver hooks found to uninstall."
    )

    return {"ok": True, "removed": changed}
