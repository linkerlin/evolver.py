"""ATP auto-buyer first-run interactive prompt.

Equivalent to ``evolver/src/atp/cliAutobuyPrompt.js``.
"""

from __future__ import annotations

import sys

from evolver.atp.auto_buyer import get_consent, set_consent


def classify() -> str:
    """Determine prompt eligibility."""
    from evolver.config import get_config

    if not sys.stdin.isatty():
        return "non_tty"
    if get_config().atp_autobuy.strip():
        return "env_set"
    ack = get_consent()
    if ack is not None:
        return "ack_present"
    return "eligible"


def run_prompt() -> None:
    """Ask the user whether to enable auto-buyer."""
    status = classify()
    if status != "eligible":
        return
    print("\n[ATP] Auto-buyer is currently disabled.")
    print("Enable automatic purchasing of ATP services?")
    print("  - Daily budget default: 50 credits")
    print("  - Per-order cap default: 10 credits")
    print("  - Cold-start protection: first 5 minutes budget halved")
    print("\nEnable? [y/N]: ", end="", flush=True)
    try:
        answer = sys.stdin.readline().strip().lower()
    except Exception:
        return
    if answer in ("y", "yes"):
        if set_consent(True):
            print("[ATP] Auto-buyer enabled. Consent saved.")
        else:
            print("[ATP] Failed to save consent.", file=sys.stderr)
    elif answer in ("n", "no"):
        if set_consent(False):
            print("[ATP] Auto-buyer disabled. Consent saved.")
        else:
            print("[ATP] Failed to save consent.", file=sys.stderr)
    else:
        print("[ATP] No change made. You will be asked again next time.")
