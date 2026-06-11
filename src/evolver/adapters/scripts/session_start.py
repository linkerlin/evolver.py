"""Session-start hook — inject relevant memories into the IDE session.

Called by the IDE when a new session starts.
Outputs JSON to stdout for the IDE to consume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["global", "workspace", "session"], default="workspace")
    args = parser.parse_args()

    try:
        from evolver.adapters.scripts.runtime_paths import find_workspace_root
        from evolver.adapters.scripts.memory_filtering import filter_relevant_memories
    except ImportError:
        # If evolver is not installed, output empty context
        print(json.dumps({"evolver_context": {"relevant_memories": [], "personality_hint": ""}}))
        sys.exit(0)

    workspace = find_workspace_root()
    memories = filter_relevant_memories(workspace=workspace, scope=args.scope, limit=5)

    output = {
        "evolver_context": {
            "workspace_id": str(workspace),
            "relevant_memories": memories,
            "personality_hint": "Evolver context injected.",
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
