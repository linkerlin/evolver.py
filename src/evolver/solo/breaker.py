"""Network breaker — the solo "no escape valve" hard cut.

Port of ``evolver/src/solo/breaker.js``.

Solo state is the ``EVOLVER_SOLO`` env var so it is process-wide, survives
across module boundaries, and is immune to import-order races with
``config.py`` (whose import-time ``Final`` constants read the env we set here).
"""

from __future__ import annotations

import os

#: Solo state env var. ``"1"`` => solo active.
SOLO_ENV = "EVOLVER_SOLO"

# Hub-URL envs cleared on activate. resolve_hub_url() also has an explicit
# solo check so the public-default fallback cannot act as an escape valve.
_HUB_URL_ENVS: tuple[str, ...] = ("A2A_HUB_URL", "EVOMAP_HUB_URL")


def activate() -> None:
    """Activate solo: hard-cut network/validator/ATP. No escape valve."""
    from evolver.config import merge_env_config, set_runtime_config_override

    os.environ[SOLO_ENV] = "1"
    for key in _HUB_URL_ENVS:
        os.environ[key] = ""
    overrides = {
        "default_hub_url": "",
        "validator_enabled": False,
        "atp": "off",
        "atp_autobuy": "off",
    }
    set_runtime_config_override(**overrides)
    merge_env_config(**overrides)


def deactivate() -> None:
    """Clear the solo flag (test helper). Does not restore prior env values."""
    from evolver.config import clear_runtime_config_overrides

    os.environ.pop(SOLO_ENV, None)
    clear_runtime_config_overrides("default_hub_url", "validator_enabled", "atp", "atp_autobuy")


def is_solo_active() -> bool:
    """True iff solo mode is active."""
    return os.environ.get(SOLO_ENV, "") == "1"
