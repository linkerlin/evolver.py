"""Shared adapter logic for IDE hook installation.

Equivalent to ``evolver/src/adapters/hookAdapter.js``.
Provides: platform detection, JSON merge, symlink safety, script copying,
Markdown section editing, and the main ``setup_hooks()`` entry point.

Design notes (Pythonic)
-----------------------
* All file operations use ``pathlib.Path``.
* JSON merging uses recursive dict updates instead of manual key traversal.
* Symlink checks use ``Path.lstat()`` (``S_ISLNK`` semantics).
* Atomic writes via temp-file + ``os.replace()``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any, cast

from evolver.gep.paths import get_workspace_root

# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------

PLATFORMS: dict[str, dict[str, str]] = {
    "cursor": {"name": "Cursor", "config_dir": ".cursor", "detector": ".cursor"},
    "claude-code": {"name": "Claude Code", "config_dir": ".claude", "detector": ".claude"},
    "codex": {"name": "Codex", "config_dir": ".codex", "detector": ".codex"},
    "kiro": {"name": "Kiro", "config_dir": ".kiro", "detector": ".kiro"},
    "opencode": {"name": "opencode", "config_dir": ".opencode", "detector": ".opencode"},
}

# Scripts that must be copied to the IDE hooks directory.
# In Python we do NOT copy .py files — instead we install wrapper scripts
# that invoke ``python -m evolver.adapters.scripts.<name>``.
HOOK_SCRIPT_NAMES = [
    "session_start.py",
    "signal_detect.py",
    "session_end.py",
    "task_recall.py",
]


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def detect_platform(cwd: Path | str | None = None) -> str | None:
    root = Path(cwd) if cwd else get_workspace_root()
    home = Path.home()
    for pid, meta in PLATFORMS.items():
        if (root / meta["detector"]).exists():
            return pid
    for pid, meta in PLATFORMS.items():
        if (home / meta["detector"]).exists():
            return pid
    return None


def resolve_config_root(platform_id: str, cwd: Path | str | None = None) -> Path:
    root = Path(cwd) if cwd else get_workspace_root()
    home = Path.home()
    meta = PLATFORMS[platform_id]
    if (root / meta["detector"]).exists():
        return root
    if (home / meta["detector"]).exists():
        return home
    return root


def load_adapter(platform_id: str) -> Any | None:
    """Dynamically import the platform-specific adapter module."""
    try:
        mod = __import__(
            f"evolver.adapters.{platform_id.replace('-', '_')}", fromlist=["install", "uninstall"]
        )
        return mod
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# JSON merge
# ---------------------------------------------------------------------------


def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for key, val in source.items():
        if isinstance(val, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def merge_with_hooks_union(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Merge two dicts, but for ``hooks.<event>`` arrays preserve user entries."""
    result = deep_merge(target, source)
    t_hooks = target.get("hooks") if isinstance(target.get("hooks"), dict) else None
    s_hooks = source.get("hooks") if isinstance(source.get("hooks"), dict) else None
    if t_hooks and s_hooks:
        for event, s_arr in s_hooks.items():
            t_arr = t_hooks.get(event)
            if isinstance(t_arr, list) and isinstance(s_arr, list):
                user_entries = [e for e in t_arr if not _is_evolver_owned(e)]
                result["hooks"][event] = user_entries + s_arr
    return result


def _is_evolver_owned(entry: Any) -> bool:
    cmds = _collect_commands(entry)
    return any(
        "evolver-session" in c or "evolver-signal" in c or "evolver-task-recall" in c for c in cmds
    )


def _collect_commands(entry: Any) -> list[str]:
    out: list[str] = []
    if isinstance(entry, dict):
        if isinstance(entry.get("command"), str):
            out.append(entry["command"])
        for h in entry.get("hooks", []):
            if isinstance(h, dict) and isinstance(h.get("command"), str):
                out.append(h["command"])
    return out


def merge_json_file(
    path: Path,
    patch: dict[str, Any],
    *,
    marker_key: str = "_evolver_managed",
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                existing = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            pass
    merged = merge_with_hooks_union(existing, patch)
    merged[marker_key] = True
    _atomic_write_json(path, merged)
    return merged


# ---------------------------------------------------------------------------
# Symlink safety
# ---------------------------------------------------------------------------


def assert_not_symlink(p: Path, label: str) -> None:
    try:
        st = p.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError(f"[setup-hooks] Cannot stat {label}: {exc}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeError(
            f"[setup-hooks] Refusing to operate: {label} {p} is a symbolic link. "
            "evolver will not follow symlinks for adapter-owned dirs — a hostile "
            "workspace could redirect writes/unlinks outside the project root. "
            "Replace it with a real directory and rerun."
        )


def assert_safe_config_dir(dir_path: Path, label: str, *, subdirs: list[str] | None = None) -> None:
    assert_not_symlink(dir_path, label)
    for sub in subdirs or []:
        assert_not_symlink(dir_path / sub, f"{label}/{sub}")


# ---------------------------------------------------------------------------
# Script helpers
# ---------------------------------------------------------------------------


def copy_hook_scripts(dest_dir: Path, evolver_root: Path | None = None) -> list[Path]:
    """Copy runtime Python scripts to the IDE hooks directory.

    In Python we copy lightweight wrapper scripts that invoke
    ``python -m evolver.adapters.scripts.<name>``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_dir = Path(__file__).with_suffix("").parent / "scripts"
    copied: list[Path] = []
    for name in HOOK_SCRIPT_NAMES:
        src = src_dir / name
        if not src.exists():
            continue
        dest = dest_dir / name
        assert_not_symlink(dest, f"hook destination {name}")
        shutil.copy2(src, dest)
        # Best-effort executable bit (no-op on Windows)
        try:
            dest.chmod(dest.stat().st_mode | 0o755)
        except OSError:
            pass
        copied.append(dest)
    return copied


def remove_hook_scripts(hooks_dir: Path) -> int:
    removed = 0
    for name in HOOK_SCRIPT_NAMES:
        p = hooks_dir / name
        try:
            if p.exists():
                p.unlink()
                removed += 1
        except OSError as exc:
            print(f"[setup-hooks] Failed to remove {p}: {exc}")
    return removed


# ---------------------------------------------------------------------------
# Markdown section editing
# ---------------------------------------------------------------------------


def append_section_to_file(file_path: Path, marker: str, content: str) -> bool:
    existing = ""
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")
    if marker in existing:
        print(f"[setup-hooks] Section already present in {file_path}, skipping.")
        return False
    separator = "\n\n" if existing and not existing.endswith("\n") else "\n"
    file_path.write_text(existing + separator + content + "\n", encoding="utf-8")
    return True


def remove_marked_section(file_path: Path, marker: str) -> bool:
    if not file_path.exists():
        return False
    raw = file_path.read_text(encoding="utf-8")
    idx = raw.find(marker)
    if idx == -1:
        return False
    scan_from = idx + len(marker)
    eol = raw.find("\n", scan_from)
    if eol != -1:
        scan_from = eol + 1
    if raw.startswith("## ", scan_from):
        eol2 = raw.find("\n", scan_from)
        if eol2 != -1:
            scan_from = eol2 + 1
    next_section = raw.find("\n## ", scan_from)
    end_idx = next_section if next_section != -1 else len(raw)
    before = raw[:idx].rstrip("\n")
    after = raw[end_idx:] if next_section != -1 else ""
    result = (before + ("" if after.startswith("\n") else "\n") if before else "") + after
    file_path.write_text(result.rstrip("\n") + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Evolver hook removal from JSON
# ---------------------------------------------------------------------------


def remove_evolver_hooks(file_path: Path, *, marker_key: str = "_evolver_managed") -> bool:
    if not file_path.exists():
        return False
    try:
        raw = file_path.read_text(encoding="utf-8").strip()
        if not raw:
            return False
        data = json.loads(raw)
        if not data.get(marker_key):
            return False
    except (json.JSONDecodeError, OSError):
        return False

    changed = False
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in list(hooks.items()):
            if isinstance(entries, list):
                before = len(entries)
                entries = [e for e in entries if not _is_evolver_owned(e)]
                if len(entries) != before:
                    changed = True
                if entries:
                    hooks[event] = entries
                else:
                    del hooks[event]
        if not hooks:
            del data["hooks"]
    del data[marker_key]
    _atomic_write_json(file_path, data)
    return changed


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.replace(path)
    except OSError:
        if path.exists():
            path.unlink()
        tmp.replace(path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def setup_hooks(
    *,
    platform: str | None = None,
    cwd: Path | str | None = None,
    force: bool = False,
    uninstall: bool = False,
    evolver_root: Path | str | None = None,
) -> dict[str, Any]:
    effective_cwd = Path(cwd) if cwd else get_workspace_root()
    effective_evolver_root = (
        Path(evolver_root) if evolver_root else Path(__file__).resolve().parents[2]
    )
    platform_id = platform or detect_platform(effective_cwd)

    if not platform_id:
        print(
            "[setup-hooks] Could not detect platform. "
            "Use --platform=cursor|claude-code|codex|kiro|opencode"
        )
        return {"ok": False, "error": "platform_not_detected"}

    meta = PLATFORMS.get(platform_id)
    if not meta:
        print(f"[setup-hooks] Unknown platform: {platform_id}")
        return {"ok": False, "error": "unknown_platform"}

    config_root = resolve_config_root(platform_id, effective_cwd)
    adapter = load_adapter(platform_id)
    if adapter is None:
        print(f"[setup-hooks] No adapter found for {platform_id}")
        return {"ok": False, "error": "no_adapter"}

    print(f"[setup-hooks] Platform: {meta['name']}")
    print(f"[setup-hooks] Config root: {config_root}")

    if uninstall:
        return cast(
            dict[str, Any],
            adapter.uninstall(config_root=config_root, evolver_root=effective_evolver_root),
        )
    return cast(
        dict[str, Any],
        adapter.install(config_root=config_root, evolver_root=effective_evolver_root, force=force),
    )
