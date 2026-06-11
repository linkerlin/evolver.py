"""Session-end hook — record session stats to the memory graph.

Called by the IDE when the session ends.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        from evolver.adapters.scripts.runtime_paths import find_workspace_root
        from evolver.gep.paths import get_memory_dir
    except ImportError:
        sys.exit(0)

    workspace = find_workspace_root()
    try:
        diff = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        diff_output = diff.stdout.strip()
    except Exception:
        diff_output = ""

    record = {
        "event": "session_end",
        "workspace": str(workspace),
        "git_diff_stat": diff_output,
    }

    memory_dir = get_memory_dir()
    signals_file = memory_dir / "signals-detected.jsonl"
    with open(signals_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps({"evolver_recorded": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
