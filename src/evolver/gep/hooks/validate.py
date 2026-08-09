"""Mechanism-contract validation for constrained candidates.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``multi_proposer.py`` ``_validate_mechanism_contract``). No Node.js
equivalent; evolver.py self-research addition (Sprint C1).

The safety chokepoint: a constrained candidate must declare exactly one hook,
the hook must belong to its declared mechanism family, the family must be
known, and the applied value must actually differ from the current one.
Violations raise :class:`MechanismContractError` — never silently accepted.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.hooks.taxonomy import (
    hook_belongs_to_family,
    known_family,
)


class MechanismContractError(Exception):
    """Raised when a constrained candidate violates the hook contract."""


def validate_mechanism_contract(
    *,
    mechanism_family: str,
    candidate_values: dict[str, Any],
    current_values: dict[str, Any] | None = None,
) -> list[str]:
    """Validate one constrained candidate; return the list of changed hooks.

    Rules (all must hold or :class:`MechanismContractError` is raised):

    * ``mechanism_family`` must be a known family,
    * ``candidate_values`` must change **exactly one** hook,
    * that hook must belong to the declared family,
    * the candidate value must differ from ``current_values`` (when given).

    Returns the hook names the candidate changes.
    """
    if not known_family(mechanism_family):
        raise MechanismContractError(
            f"unknown mechanism_family: {mechanism_family!r}"
        )

    if not isinstance(candidate_values, dict) or not candidate_values:
        raise MechanismContractError(
            "candidate_values must be a non-empty dict of hook → value"
        )
    if len(candidate_values) > 1:
        raise MechanismContractError(
            f"exactly one hook per candidate, got {sorted(candidate_values)}"
        )

    (hook, value) = next(iter(candidate_values.items()))
    if not isinstance(hook, str) or not hook:
        raise MechanismContractError("hook name must be a non-empty string")
    if not hook_belongs_to_family(mechanism_family, hook):
        raise MechanismContractError(
            f"hook {hook!r} does not belong to family "
            f"{mechanism_family!r}"
        )

    if current_values is not None:
        current = current_values.get(hook)
        if current == value:
            raise MechanismContractError(
                f"candidate value for {hook!r} does not differ from current"
            )

    return [hook]


__all__ = [
    "MechanismContractError",
    "validate_mechanism_contract",
]
