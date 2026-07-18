"""Claude Code IDE adapter.

Equivalent to ``evolver/src/adapters/claudeCode.js``.
Installs/uninstalls evolver hooks into ``.claude/settings.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.adapters.hook_adapter import (
    assert_safe_config_dir,
    copy_hook_scripts,
    merge_json_file,
    remove_hook_scripts,
    remove_marked_section,
)

HOOK_SCRIPTS_DIR_NAME = "hooks"
EVOLVER_MARKER = "<!-- evolver-evolution-memory -->"


def build_hooks(evolver_root: Path) -> dict[str, Any]:
    """Build the Claude Code hooks configuration."""
    from evolver.uv_runtime import hook_command_string

    return {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command_string(
                                "evolver.adapters.scripts.session_start"
                            ),
                            "timeout": 3,
                        },
                    ],
                },
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command_string("evolver.adapters.scripts.task_recall"),
                            "timeout": 5,
                        },
                    ],
                },
            ],
            "PostToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command_string(
                                "evolver.adapters.scripts.signal_detect"
                            ),
                            "timeout": 2,
                        },
                    ],
                },
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command_string("evolver.adapters.scripts.session_end"),
                            "timeout": 8,
                        },
                    ],
                },
            ],
        },
    }


def build_md_section() -> str:
    return f"""{EVOLVER_MARKER}
## Evolution Memory (Evolver)

This project uses evolver for self-evolution. Hooks automatically:
1. Inject recent evolution memory at session start
2. Detect evolution signals during file edits
3. Record outcomes at session end
4. (Opt-in) Surface matching distilled capabilities for each prompt — set
   `EVOLVER_RECALL_MODE=shadow` to preview, `enforce` to inject (default off).

For substantive tasks, call `gep_recall` before work and `gep_record_outcome` after.
Signals: log_error, perf_bottleneck, user_feature_request, capability_gap,
deployment_issue, test_failure."""


def install(
    *,
    config_root: Path,
    evolver_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    claude_dir = config_root / ".claude"
    settings_path = claude_dir / "settings.json"
    hooks_dir = claude_dir / HOOK_SCRIPTS_DIR_NAME
    claude_md_path = config_root / "CLAUDE.md"
    assert_safe_config_dir(claude_dir, ".claude", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    if not force and settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if existing.get("_evolver_managed"):
                print("[claude-code] Evolver hooks already installed. Use --force to overwrite.")
                return {"ok": True, "skipped": True}
        except (json.JSONDecodeError, OSError):
            pass

    claude_dir.mkdir(parents=True, exist_ok=True)

    hooks_cfg = build_hooks(evolver_root)
    merge_json_file(settings_path, hooks_cfg)
    print(f"[claude-code] Wrote {settings_path}")

    copied = copy_hook_scripts(hooks_dir, evolver_root)
    print(f"[claude-code] Copied {len(copied)} hook scripts to {hooks_dir}")

    from evolver.adapters.hook_adapter import append_section_to_file

    injected = append_section_to_file(claude_md_path, EVOLVER_MARKER, build_md_section())
    if injected:
        print(f"[claude-code] Injected evolution section into {claude_md_path}")

    print("[claude-code] Installation complete.")

    return {
        "ok": True,
        "platform": "claude-code",
        "files": [str(settings_path), str(claude_md_path)] + [str(c) for c in copied],
    }


def uninstall(
    *,
    config_root: Path,
    evolver_root: Path,
) -> dict[str, Any]:
    claude_dir = config_root / ".claude"
    settings_path = claude_dir / "settings.json"
    hooks_dir = claude_dir / HOOK_SCRIPTS_DIR_NAME
    claude_md_path = config_root / "CLAUDE.md"
    assert_safe_config_dir(claude_dir, ".claude", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    changed = False

    # Strip evolver entries from settings.json with nested-hook awareness.
    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            touched = False
            hooks = data.get("hooks")
            if isinstance(hooks, dict):
                for event in list(hooks.keys()):
                    entries = hooks[event]
                    if isinstance(entries, list):
                        before_len = len(entries)
                        cleaned_entries: list[Any] = []
                        for matcher in entries:
                            if not isinstance(matcher, dict):
                                cleaned_entries.append(matcher)
                                continue
                            inner_hooks = matcher.get("hooks")
                            if not isinstance(inner_hooks, list):
                                cleaned_entries.append(matcher)
                                continue
                            inner_before = len(inner_hooks)
                            filtered = [
                                h
                                for h in inner_hooks
                                if not (
                                    isinstance(h, dict)
                                    and isinstance(h.get("command"), str)
                                    and (
                                        "evolver-session" in h["command"]
                                        or "evolver-signal" in h["command"]
                                        or "evolver-task-recall" in h["command"]
                                    )
                                )
                            ]
                            if len(filtered) != inner_before:
                                touched = True
                            if filtered:
                                cleaned_entries.append({**matcher, "hooks": filtered})
                        if len(cleaned_entries) != before_len:
                            touched = True
                        if cleaned_entries:
                            hooks[event] = cleaned_entries
                        else:
                            del hooks[event]
                if not hooks:
                    del data["hooks"]
            if data.get("_evolver_managed"):
                del data["_evolver_managed"]
                touched = True
            if touched:
                tmp = settings_path.with_suffix(f".tmp-{settings_path.name}")
                tmp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                tmp.replace(settings_path)
                changed = True
    except Exception as exc:
        print(f"[claude-code] Failed to clean {settings_path}: {exc}")

    scripts = remove_hook_scripts(hooks_dir)
    if scripts > 0:
        changed = True
    try:
        if hooks_dir.exists() and not any(hooks_dir.iterdir()):
            hooks_dir.rmdir()
    except OSError:
        pass

    if remove_marked_section(claude_md_path, EVOLVER_MARKER):
        changed = True

    print(
        "[claude-code] Uninstalled evolver hooks."
        if changed
        else "[claude-code] No evolver hooks found to uninstall."
    )

    return {"ok": True, "removed": changed}
