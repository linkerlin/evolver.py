"""Path sanitization — hide absolute paths (e.g. usernames)."""

from __future__ import annotations

import re
from pathlib import Path


def sanitize_path(path: str | Path) -> str:
    r"""Convert an absolute path to a relative or anonymized string.

    - If *path* is under the current working directory, return a relative path.
    - Otherwise replace the home directory prefix with ``~``.
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
        return f"~/{rel}".replace("\\", "/")
    except ValueError:
        pass

    # Last resort: keep filename only
    return p.name
