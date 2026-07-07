"""Solo mode — constrained-wild offline operation (``--solo`` / "Mad Dog").

Behaviour-equivalent port of ``evolver/src/solo/`` (``breaker.js`` +
``gitGuard.js``).

When active, solo hard-cuts the network with **no escape valve** — a
user-provided ``A2A_HUB_URL`` is ignored — disables the validator daemon and
ATP auto-spend, and restricts git to local-only subcommands. Activation
happens in :func:`evolver.cli.main` before any service reads config; the
guards are re-asserted in cycle path (see ``post_cycle``, ``git_ops``).
"""

from __future__ import annotations

from evolver.solo.breaker import activate, deactivate, is_solo_active
from evolver.solo.git_guard import NETWORK_GIT_SUBCOMMANDS, is_network_git_allowed

__all__ = [
    "NETWORK_GIT_SUBCOMMANDS",
    "activate",
    "deactivate",
    "is_network_git_allowed",
    "is_solo_active",
    "print_solo_banner",
]


def print_solo_banner() -> None:
    """Emit the solo startup banner (goes to stdout; matched by solo contract)."""
    print("[Solo] Mad Dog · 受约束的野性模式已启动")
    print("[Solo] 断网模式 · 禁ATP · 仅本机git可追踪")
    print("[Solo] 断网 · 禁ATP")
    print("[Solo] 仅本机git可追踪")
