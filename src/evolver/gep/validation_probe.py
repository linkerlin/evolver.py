"""Layout-aware validation probe for soft-default UX.

Discovers project check roots (src/, lib/, tests/, etc.) and adapts cascade
commands to match the actual project layout. Never creates directories.

Covers beginner-soft-default design (2026-10-31):
- No forced layout (never require src/)
- Skip stages with warnings when paths or tools missing
- Rewrite args when alternative roots exist (e.g. lib/ instead of src/)
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


# Conventional check roots we discover (order matters for priority)
_CONVENTIONAL_ROOTS = [
    "src",
    "lib",
    "tests",
    "test",
]


def discover_check_roots(cwd: Path) -> list[str]:
    """Discover conventional check roots in the project.

    Returns a list of directory names (not paths) that exist at the top level
    of cwd. Never creates directories; pure discovery.

    Args:
        cwd: Project root directory to scan

    Returns:
        List of discovered root names (e.g. ["src", "tests"])
    """
    roots: list[str] = []
    for name in _CONVENTIONAL_ROOTS:
        candidate = cwd / name
        if candidate.is_dir():
            roots.append(name)
    return roots


def _rewrite_path_args(
    command: list[str], from_paths: list[str], to_paths: list[str]
) -> list[str]:
    """Rewrite path arguments in a command.

    Replace occurrences of from_paths with to_paths in the command argv.
    Handles both exact matches and trailing path components.

    Args:
        command: Command argv (e.g. ["ruff", "check", "src", "tests"])
        from_paths: Paths to replace (e.g. ["src"])
        to_paths: Replacement paths (e.g. ["lib"])

    Returns:
        New command with rewritten paths
    """
    if not from_paths or not to_paths:
        return command

    result = []
    for arg in command:
        replaced = arg
        for from_path in from_paths:
            if arg == from_path:
                # Exact match: replace with first to_path
                replaced = to_paths[0] if to_paths else arg
                break
        result.append(replaced)
    return result


def _filter_existing_paths(command: list[str], existing_roots: set[str]) -> list[str]:
    """Filter command args to only include existing paths.

    Args:
        command: Command argv
        existing_roots: Set of existing root directory names

    Returns:
        Command with non-existent path args removed, or empty list if no paths remain
    """
    if not command:
        return []

    tool = command[0]
    result = [tool]
    found_any_path = False

    for arg in command[1:]:
        # Keep flags and options (start with -)
        if arg.startswith("-"):
            result.append(arg)
        # Keep path args that exist
        elif arg in existing_roots:
            result.append(arg)
            found_any_path = True
        # Check if this is a potential path arg from our conventions
        elif arg in _CONVENTIONAL_ROOTS:
            # This is a conventional root that doesn't exist - skip it
            pass
        else:
            # Keep other args (subcommands like "check", option values, etc.)
            result.append(arg)

    # If we didn't find any actual paths and the command expects paths,
    # return empty to signal skip
    if not found_any_path and len(result) > 1:
        # For tools like ruff/mypy that need paths, check if we only have
        # the tool and maybe subcommands, but no actual paths
        return []

    return result if len(result) > 1 else []


def adapt_cascade_commands(
    commands: list[dict[str, Any]], cwd: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    """Adapt cascade commands to project layout.

    Discovers check roots and rewrites/skips commands as needed:
    - If src/ missing but lib/ present: rewrite src → lib
    - If path arguments don't exist: filter them out
    - If no runnable args remain: skip command with warning
    - Preserve timeout_ms and other dict fields

    Never creates directories. Returns adapted commands and warnings.

    Args:
        commands: Cascade command specs (list of dicts with "command" key)
        cwd: Project root directory

    Returns:
        Tuple of (adapted_commands, warnings):
        - adapted_commands: Runnable command specs
        - warnings: List of warning messages for skipped/adapted stages
    """
    if not commands:
        return [], []

    roots = discover_check_roots(cwd)
    roots_set = set(roots)
    adapted: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Check if we have src/ or alternatives
    has_src = "src" in roots_set
    has_lib = "lib" in roots_set
    has_tests = "tests" in roots_set or "test" in roots_set

    for cmd_spec in commands:
        # Deep copy to avoid mutating input
        spec = copy.deepcopy(cmd_spec)
        command = spec.get("command", [])

        if not command or not isinstance(command, list):
            continue

        tool = command[0] if command else ""

        # Detect Python tools that typically use src/tests
        is_python_tool = tool in ("ruff", "mypy", "pytest", "black", "isort", "pylint")

        # For Python tools, adapt based on layout
        if is_python_tool:
            original_command = command.copy()

            # Special handling for pytest
            if tool == "pytest":
                # Keep pytest only if we have tests/, or if there are .py files that might have tests
                # In a truly empty project, skip it
                if has_tests:
                    spec["command"] = original_command
                    adapted.append(spec)
                else:
                    # No tests/ directory - this is a skip with warning
                    warnings.append(
                        f"pytest: tests/ directory not found, skipping pytest"
                    )
                continue

            # Rewrite src → lib if lib exists but src doesn't
            if not has_src and has_lib and "src" in command:
                command = _rewrite_path_args(command, ["src"], ["lib"])

            # Filter to existing paths (for ruff, mypy)
            command = _filter_existing_paths(command, roots_set)

            # Check if we still have a runnable command
            if not command or len(command) <= 1:
                # Skip this stage entirely
                warnings.append(
                    f"{tool}: no suitable paths found "
                    f"(original: {' '.join(original_command[1:])})"
                )
                continue

            spec["command"] = command

        # Keep non-Python tools as-is
        adapted.append(spec)

    return adapted, warnings
