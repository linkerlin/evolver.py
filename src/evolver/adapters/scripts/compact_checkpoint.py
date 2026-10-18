"""PreCompact hook — hold native compaction until the working memory is written.

Claude Code fires this before it compacts the conversation and reads the
decision from stdout: ``{"decision": "block", "reason": ...}`` holds the
compaction, ``{}`` lets it proceed. The engine blocks until the host has
called ``swarm_checkpoint_working``, at most once per request (see
``compact_gate.precompact_decision``). The marker and ready files live under
the same ``<EVOLUTION_DIR>/`` the MCP server uses, soak routing included.

No Node.js equivalent.
"""

from __future__ import annotations

import json


def main() -> int:
    from evolver.gep.compact_gate import precompact_decision
    from evolver.ops.soak_env import maybe_route_to_soak

    maybe_route_to_soak()
    print(json.dumps(precompact_decision(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
