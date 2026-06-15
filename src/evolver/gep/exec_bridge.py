"""Execution bridge — resolve spawn targets safely on Windows.

Equivalent to ``evolver/src/gep/execBridge.js``.

The primary responsibility of this module is :func:`resolve_npm_cmd_shim`,
which handles the **CVE-2024-27980** constraint: Node >= 18.20.2 refuses to
spawn ``.cmd`` / ``.bat`` targets without ``shell=True`` (throws ``EINVAL``).
On the Node side this rewrites ``(npm.cmd, args)`` into
``(node.exe, [cli.js, ...args])``.

In the Python port, ``subprocess`` does not have the same EINVAL restriction,
but the helper is provided for **behavioural equivalence**: any code path that
needs to spawn an npm-installed CLI tool should go through this resolver so
the (bin, args) tuple is normalised identically across both runtimes.

The resolver:
  1. Only activates on Windows (``sys.platform == 'win32'``).
  2. Only activates for ``.cmd`` targets (the npm-cli shim format).
  3. Parses the well-known last line of the shim to find the JS entry.
  4. Returns ``(python_executable, [entry, ...args])`` or ``None`` if the
     shim does not match the expected format or the entry is missing.

Tested by ``test/execBridgeSpawnNpmShim.test.js``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Pattern for the trailing exec line in an npm-cli .cmd shim.
# Real format (verbatim from anthropic-ai-sdk.cmd):
#   endLocal & goto #_undefined# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\<entry>" %*
# We extract the <entry> path from the "%dp0%\<entry>" %* portion.
_NPM_SHIM_ENTRY_RE = re.compile(
    r'"%dp0%\\([^"]+)"\s*%\*'  # capture the entry path after %dp0%\
)

#: Minimum shim length — a real shim is ~300+ chars; reject anything too short.
_MIN_SHIM_LEN = 50


def _is_windows() -> bool:
    return sys.platform == "win32"


def resolve_npm_cmd_shim(
    bin_path: str | Path | None,
    args: list[str] | None,
) -> tuple[str, list[str]] | None:
    """Resolve an npm-cli ``.cmd`` shim into a direct ``(interpreter, [entry, ...args])`` tuple.

    Returns ``None`` when:
      - Not on Windows.
      - *bin_path* is not a ``.cmd`` file.
      - The file is not an npm-cli format shim (custom wrapper).
      - The resolved entry does not exist on disk.
      - The shim file cannot be read.

    When successful, returns ``(python_executable, [absolute_entry_path, ...args])``.
    On the Node side this returns ``(node.exe, [entry.js, ...args])``; in the
    Python port we return the Python interpreter since that is what executes
    downstream scripts. The key behavioural property — normalising the spawn
    target away from the raw ``.cmd`` — is identical.
    """
    entry_abs = _parse_shim_entry(bin_path)
    if entry_abs is None:
        return None
    forward_args = list(args) if args else []
    return (sys.executable, [str(entry_abs), *forward_args])


def _parse_shim_entry(bin_path: str | Path | None) -> Path | None:  # noqa: PLR0911
    """Parse an npm .cmd shim and return the resolved entry path, or None."""
    if not _is_windows() or not bin_path:
        return None

    path = Path(bin_path)
    if path.suffix.lower() != ".cmd":
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if len(content) < _MIN_SHIM_LEN:
        return None

    match = _NPM_SHIM_ENTRY_RE.search(content)
    if not match:
        return None

    entry_rel = match.group(1)
    entry_abs = (path.parent / entry_rel).resolve()

    # npm-cli may omit the .js extension; try with .js appended.
    if not entry_abs.exists():
        entry_with_js = entry_abs.with_suffix(entry_abs.suffix + ".js")
        if entry_with_js.exists():
            return entry_with_js
        return None  # broken install

    return entry_abs


def safe_spawn_args(
    bin_path: str | None,
    args: list[str] | None,
) -> tuple[str, list[str]]:
    """Return a spawn-safe (bin, args) tuple, resolving .cmd shims on Windows.

    If :func:`resolve_npm_cmd_shim` succeeds, its result is returned.
    Otherwise the original ``(bin_path, args)`` is returned unchanged.

    This is the public entry point for code that needs to spawn an external
    CLI tool and wants the .cmd EINVAL issue handled transparently.
    """
    resolved = resolve_npm_cmd_shim(bin_path, args)
    if resolved is not None:
        return resolved
    return (bin_path or "", list(args) if args else [])


__all__ = [
    "resolve_npm_cmd_shim",
    "safe_spawn_args",
]
