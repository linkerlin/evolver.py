"""Path sanitization — hide absolute paths (e.g. usernames)."""

from __future__ import annotations

import tempfile
from pathlib import Path


def sanitize_path(path: str | Path) -> str:
    r"""Convert an absolute path to a relative or anonymized string.

    - If *path* is under the current working directory, return a relative path.
    - Otherwise replace the home directory prefix with ``~``.
    - Paths under the OS temp dir (including Windows
      ``~/AppData/Local/Temp/...``) collapse to the filename only so observer
      UI does not leak long temp prefixes.
    - On Windows, also anonymize ``C:\Users\<username>`` → ``~``.
    """
    p = Path(path).resolve()
    try:
        rel = p.relative_to(Path.cwd().resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        pass

    home = Path.home().resolve()
    try:
        rel = p.relative_to(home)
        rel_s = str(rel).replace("\\", "/")
        lower = rel_s.lower()
        # Windows profile temp: prefer basename over ~/AppData/Local/Temp/...
        if lower.startswith("appdata/local/temp/") or lower.startswith("appdata/local/tmp/"):
            return p.name
        return f"~/{rel_s}"
    except ValueError:
        pass

    try:
        p.relative_to(Path(tempfile.gettempdir()).resolve())
        return p.name
    except ValueError:
        pass

    # Last resort: keep filename only
    return p.name
