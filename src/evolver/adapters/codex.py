"""Codex IDE adapter.

Equivalent to ``evolver/src/adapters/codex.js``.
Installs/uninstalls evolver hooks into ``.codex/hooks.json``
and toggles ``codex_hooks`` in ``config.toml``.
"""

from __future__ import annotations

import json
import re
import sys
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


def build_hooks_json(evolver_root: Path) -> dict[str, Any]:
    scripts_base = ".codex/hooks"
    executable = sys.executable.replace("\\", "/")
    return {
        "hooks": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": f"{executable} -m evolver.adapters.scripts.session_start",
                    "timeout": 3,
                },
            ],
            "PostToolUse": [
                {
                    "type": "command",
                    "command": f"{executable} -m evolver.adapters.scripts.signal_detect",
                    "timeout": 2,
                },
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": f"{executable} -m evolver.adapters.scripts.session_end",
                    "timeout": 8,
                },
            ],
        },
    }


def _ensure_config_toml(codex_dir: Path) -> bool:
    codex_dir.mkdir(parents=True, exist_ok=True)
    toml_path = codex_dir / "config.toml"
    content = ""
    if toml_path.exists():
        try:
            content = toml_path.read_text(encoding="utf-8")
        except OSError:
            pass

    if re.search(r"codex_hooks\s*=\s*true", content, re.IGNORECASE):
        return False

    if re.search(r"\[features\]", content):
        content = re.sub(r"\[features\]", "[features]\ncodex_hooks = true", content, count=1)
    else:
        separator = "\n\n" if content and not content.endswith("\n") else "\n" if content else ""
        content += separator + "[features]\ncodex_hooks = true\n"

    toml_path.write_text(content, encoding="utf-8")
    return True


def _clean_config_toml(codex_dir: Path) -> bool:
    toml_path = codex_dir / "config.toml"
    if not toml_path.exists():
        return False
    try:
        content = toml_path.read_text(encoding="utf-8")
    except OSError:
        return False

    if not re.search(r"codex_hooks\s*=\s*true", content, re.IGNORECASE):
        return False

    # Drop the codex_hooks = true line
    next_text = re.sub(
        r"^\s*codex_hooks\s*=\s*true\s*\n?",
        "",
        content,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Drop an empty [features] block
    next_text = re.sub(r"(^|\n)\[features\]\s*\n(?=\s*\[)", r"\1", next_text)
    next_text = re.sub(r"(^|\n)\[features\]\s*$", r"\1", next_text)
    next_text = re.sub(r"\n{3,}", "\n\n", next_text).rstrip("\n")
    if next_text:
        next_text += "\n"
    toml_path.write_text(next_text, encoding="utf-8")
    return True


def build_agents_md_section() -> str:
    return f"""{EVOLVER_MARKER}
## Evolution Memory (Evolver)

This project uses evolver for self-evolution. Hooks automatically:
1. Inject recent evolution memory at session start
2. Detect evolution signals during file edits
3. Record outcomes at session end

For substantive tasks, call `gep_recall` before work and `gep_record_outcome` after.
Signals: log_error, perf_bottleneck, user_feature_request, capability_gap,
deployment_issue, test_failure."""


def install(
    *,
    config_root: Path,
    evolver_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    codex_dir = config_root / ".codex"
    hooks_json_path = codex_dir / "hooks.json"
    hooks_dir = codex_dir / HOOK_SCRIPTS_DIR_NAME
    agents_md_path = config_root / "AGENTS.md"
    assert_safe_config_dir(codex_dir, ".codex", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    if not force and hooks_json_path.exists():
        try:
            existing = json.loads(hooks_json_path.read_text(encoding="utf-8"))
            if existing.get("_evolver_managed"):
                print("[codex] Evolver hooks already installed. Use --force to overwrite.")
                return {"ok": True, "skipped": True}
        except (json.JSONDecodeError, OSError):
            pass

    codex_dir.mkdir(parents=True, exist_ok=True)

    hooks_cfg = build_hooks_json(evolver_root)
    merge_json_file(hooks_json_path, hooks_cfg)
    print(f"[codex] Wrote {hooks_json_path}")

    copied = copy_hook_scripts(hooks_dir, evolver_root)
    print(f"[codex] Copied {len(copied)} hook scripts to {hooks_dir}")

    toml_changed = _ensure_config_toml(codex_dir)
    if toml_changed:
        print("[codex] Enabled codex_hooks in config.toml")

    from evolver.adapters.hook_adapter import append_section_to_file

    injected = append_section_to_file(agents_md_path, EVOLVER_MARKER, build_agents_md_section())
    if injected:
        print(f"[codex] Injected evolution section into {agents_md_path}")

    print("[codex] Installation complete.")

    return {
        "ok": True,
        "platform": "codex",
        "files": [str(hooks_json_path), str(codex_dir / "config.toml"), str(agents_md_path)]
        + [str(c) for c in copied],
    }


def uninstall(
    *,
    config_root: Path,
    evolver_root: Path,
) -> dict[str, Any]:
    codex_dir = config_root / ".codex"
    hooks_json_path = codex_dir / "hooks.json"
    hooks_dir = codex_dir / HOOK_SCRIPTS_DIR_NAME
    agents_md_path = config_root / "AGENTS.md"
    assert_safe_config_dir(codex_dir, ".codex", subdirs=[HOOK_SCRIPTS_DIR_NAME])

    changed = False

    try:
        if hooks_json_path.exists():
            data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
            touched = False
            hooks = data.get("hooks")
            if isinstance(hooks, dict):
                for event in list(hooks.keys()):
                    entries = hooks[event]
                    if isinstance(entries, list):
                        before = len(entries)
                        filtered = [
                            h
                            for h in entries
                            if not (
                                isinstance(h, dict)
                                and isinstance(h.get("command"), str)
                                and (
                                    "evolver-session" in h["command"]
                                    or "evolver-signal" in h["command"]
                                )
                            )
                        ]
                        if len(filtered) != before:
                            touched = True
                        if filtered:
                            hooks[event] = filtered
                        else:
                            del hooks[event]
                if not hooks:
                    del data["hooks"]
            if data.get("_evolver_managed"):
                del data["_evolver_managed"]
                touched = True
            if touched:
                tmp = hooks_json_path.with_suffix(f".tmp-{hooks_json_path.name}")
                tmp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                tmp.replace(hooks_json_path)
                changed = True
    except Exception as exc:
        print(f"[codex] Failed to clean {hooks_json_path}: {exc}")

    scripts = remove_hook_scripts(hooks_dir)
    if scripts > 0:
        changed = True
    try:
        if hooks_dir.exists() and not any(hooks_dir.iterdir()):
            hooks_dir.rmdir()
    except OSError:
        pass

    if _clean_config_toml(codex_dir):
        print("[codex] Removed codex_hooks flag from config.toml")
        changed = True

    if remove_marked_section(agents_md_path, EVOLVER_MARKER):
        changed = True

    print(
        "[codex] Uninstalled evolver hooks."
        if changed
        else "[codex] No evolver hooks found to uninstall."
    )

    return {"ok": True, "removed": changed}
