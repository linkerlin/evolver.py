"""JSONL streaming parser — supports large files (> 100 MB) via lazy iteration."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def stream_jsonl(
    path: Path, *, limit: int | None = None, since: float | None = None
) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL file lazily.

    *limit* — maximum number of lines to yield.
    *since* — only yield rows whose ``timestamp`` >= *since*.
    """
    if not path.exists():
        return

    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("[JSONL] Skip malformed line in %s: %s", path, exc)
                continue
            if since is not None and obj.get("timestamp", 0) < since:
                continue
            yield obj
            count += 1
            if limit is not None and count >= limit:
                break
