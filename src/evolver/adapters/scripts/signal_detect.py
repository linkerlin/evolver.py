"""Signal-detect hook — detect evolution signals from IDE output.

Called by the IDE on file save or terminal output change.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Layer-1 regex patterns (same as gep/signals.py)
PATTERNS = {
    "error": re.compile(r"error|exception|traceback|failure|failed", re.IGNORECASE),
    "test_fail": re.compile(r"test.*fail|assertion.*error|pytest.*fail", re.IGNORECASE),
    "type_error": re.compile(r"typeerror|type.*error", re.IGNORECASE),
    "lint": re.compile(r"lint.*error|eslint|flake8|ruff.*error", re.IGNORECASE),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Path to the saved file")
    args = parser.parse_args()

    signals: list[dict[str, str]] = []
    # Simple scan: if a file was saved, check its name for clues
    if args.file:
        fname = Path(args.file).name.lower()
        if "test" in fname:
            signals.append({"signal": "test_run", "source": "file_save", "file": args.file})

    # Output detected signals
    print(json.dumps({"evolver_signals": signals}, ensure_ascii=False))


if __name__ == "__main__":
    main()
