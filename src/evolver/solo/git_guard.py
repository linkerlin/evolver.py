"""Local-git-only guard — solo blocks network git subcommands.

Port of ``evolver/src/solo/gitGuard.js``. Solo permits only local git
operations; ``fetch``/``push``/``pull``/``clone``/``remote`` are refused at
the :func:`evolver.gep.git_ops.run_cmd` choke point so a network git op can
never leak a change off-machine during a solo run.
"""

from __future__ import annotations

from evolver.solo.breaker import is_solo_active

#: Git subcommands that touch the network and are blocked under solo.
NETWORK_GIT_SUBCOMMANDS: frozenset[str] = frozenset({"fetch", "push", "pull", "clone", "remote"})


def is_network_git_allowed() -> bool:
    """True iff a network git operation is permitted (always False under solo)."""
    return not is_solo_active()


def guard_git_subcommand(sub: str | None) -> str | None:
    """Return a blocking reason if *sub* is forbidden under solo, else ``None``."""
    if not is_solo_active():
        return None
    if sub and sub in NETWORK_GIT_SUBCOMMANDS:
        return f"solo: network git '{sub}' blocked (local-git-only)"
    return None
