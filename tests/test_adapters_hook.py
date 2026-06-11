"""Tests for evolver.adapters.hook_adapter and cursor adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.adapters import hook_adapter

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def test_detect_platform_cursor(temp_workspace: Path) -> None:
    (temp_workspace / ".cursor").mkdir()
    result = hook_adapter.detect_platform(temp_workspace)
    assert result == "cursor"


def test_detect_platform_none(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure home directory does not match any platform
    monkeypatch.setattr(hook_adapter.Path, "home", lambda: temp_workspace)
    result = hook_adapter.detect_platform(temp_workspace)
    assert result is None


# ---------------------------------------------------------------------------
# JSON merge
# ---------------------------------------------------------------------------


def test_deep_merge() -> None:
    target = {"a": 1, "b": {"c": 2}}
    source = {"b": {"d": 3}, "e": 4}
    result = hook_adapter.deep_merge(target, source)
    assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}


def test_merge_json_file(temp_workspace: Path) -> None:
    path = temp_workspace / "test.json"
    hook_adapter.merge_json_file(path, {"hooks": {"start": [{"command": "echo hi"}]}})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["_evolver_managed"] is True
    assert len(data["hooks"]["start"]) == 1


# ---------------------------------------------------------------------------
# Symlink safety
# ---------------------------------------------------------------------------


def test_assert_not_symlink_ok(temp_workspace: Path) -> None:
    hook_adapter.assert_not_symlink(temp_workspace, "test")


def test_assert_not_symlink_rejects_symlink(temp_workspace: Path) -> None:
    real = temp_workspace / "real"
    real.mkdir()
    link = temp_workspace / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(RuntimeError):
        hook_adapter.assert_not_symlink(link, "link")


# ---------------------------------------------------------------------------
# Markdown section editing
# ---------------------------------------------------------------------------


def test_append_and_remove_section(temp_workspace: Path) -> None:
    path = temp_workspace / "AGENTS.md"
    path.write_text("# Agent\n", encoding="utf-8")
    marker = "<!-- evolver-start -->"
    content = "<!-- evolver-start -->\n## Evolution Memory\n\nContext here.\n<!-- evolver-end -->"
    assert hook_adapter.append_section_to_file(path, marker, content) is True
    text = path.read_text(encoding="utf-8")
    assert marker in text

    assert hook_adapter.remove_marked_section(path, marker) is True
    text = path.read_text(encoding="utf-8")
    assert marker not in text


def test_append_section_idempotent(temp_workspace: Path) -> None:
    path = temp_workspace / "AGENTS.md"
    path.write_text("# Agent\n", encoding="utf-8")
    marker = "<!-- evolver-start -->"
    hook_adapter.append_section_to_file(
        path, marker, "<!-- evolver-start -->\ncontent\n<!-- evolver-end -->"
    )
    result = hook_adapter.append_section_to_file(
        path, marker, "<!-- evolver-start -->\ncontent\n<!-- evolver-end -->"
    )
    assert result is False


# ---------------------------------------------------------------------------
# Evolver hook removal
# ---------------------------------------------------------------------------


def test_remove_evolver_hooks(temp_workspace: Path) -> None:
    path = temp_workspace / "hooks.json"
    data = {
        "_evolver_managed": True,
        "hooks": {
            "start": [
                {"command": "node evolver-session-start.js"},
                {"command": "user-hook"},
            ]
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    changed = hook_adapter.remove_evolver_hooks(path)
    assert changed is True
    result = json.loads(path.read_text(encoding="utf-8"))
    assert "_evolver_managed" not in result
    assert len(result["hooks"]["start"]) == 1
    assert result["hooks"]["start"][0]["command"] == "user-hook"


# ---------------------------------------------------------------------------
# Cursor adapter
# ---------------------------------------------------------------------------


def test_cursor_install(temp_workspace: Path) -> None:
    from evolver.adapters import cursor

    result = cursor.install(config_root=temp_workspace, evolver_root=temp_workspace)
    assert result["ok"] is True
    assert (temp_workspace / ".cursor" / "hooks.json").exists()


def test_cursor_uninstall(temp_workspace: Path) -> None:
    from evolver.adapters import cursor

    cursor.install(config_root=temp_workspace, evolver_root=temp_workspace)
    result = cursor.uninstall(config_root=temp_workspace, evolver_root=temp_workspace)
    assert result["ok"] is True
    assert result["removed"] is True


def test_cursor_install_skips_when_already_installed(temp_workspace: Path) -> None:
    from evolver.adapters import cursor

    cursor.install(config_root=temp_workspace, evolver_root=temp_workspace)
    result = cursor.install(config_root=temp_workspace, evolver_root=temp_workspace, force=False)
    assert result["skipped"] is True


# ---------------------------------------------------------------------------
# Runtime scripts
# ---------------------------------------------------------------------------


def test_runtime_paths_find_workspace(temp_workspace: Path) -> None:
    # Create a git repo
    import subprocess

    from evolver.adapters.scripts.runtime_paths import find_workspace_root

    subprocess.run(["git", "init"], cwd=temp_workspace, capture_output=True, check=False)
    result = find_workspace_root(temp_workspace)
    assert result == temp_workspace


def test_memory_filtering_empty(temp_workspace: Path) -> None:
    from evolver.adapters.scripts.memory_filtering import filter_relevant_memories

    result = filter_relevant_memories(workspace=temp_workspace, limit=5)
    assert result == []
