"""Local node secret reset utility.

Equivalent to the Node `reset-local-secret` command.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any


def _generate_secret(length: int = 32) -> str:
    """Generate a cryptographically secure hex secret."""
    return secrets.token_hex(length)


def _generate_node_id() -> str:
    """Generate a short random node id."""
    return f"node_{secrets.token_hex(8)}"


def _update_env_file(env_path: Path, key: str, value: str) -> bool:
    """Update or append a key in a .env file. Returns True if file was modified."""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def reset_local_secret(
    *,
    project_dir: str | Path = ".",
    also_node_id: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Reset the local A2A_NODE_SECRET (and optionally A2A_NODE_ID).

    Returns a result dict with ``ok``, ``secret``, ``node_id``, and ``env_path``.
    """
    pdir = Path(project_dir).resolve()
    if not pdir.is_dir():
        return {"ok": False, "error": f"Not a directory: {pdir}"}

    env_path = pdir / ".env"
    new_secret = _generate_secret()
    new_node_id = _generate_node_id() if also_node_id else None

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "secret": new_secret,
            "node_id": new_node_id,
            "env_path": str(env_path),
        }

    _update_env_file(env_path, "A2A_NODE_SECRET", new_secret)
    if also_node_id and new_node_id:
        _update_env_file(env_path, "A2A_NODE_ID", new_node_id)

    return {
        "ok": True,
        "secret": new_secret,
        "node_id": new_node_id,
        "env_path": str(env_path),
    }
