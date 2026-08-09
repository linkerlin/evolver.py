"""Closed-vocabulary hook taxonomy.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``proposer/src/self_harness_proposer/hooks.py``). No Node.js equivalent;
evolver.py self-research addition (Sprint C1).

Bounding LLM codegen to a taxonomy of named hooks (rather than arbitrary
patches) is the key safety mechanism that lets an LLM edit its own runtime.
A *hook* names a concrete editable surface; ``apply_candidate_values``
(:mod:`evolver.gep.hooks.apply`) enforces "exactly one hook per candidate".

The taxonomy is evolver.py-original (NOT Self-Harness's harness function
names). Sprint C1 lands two families (``prompt_instruction`` — AST rewrite of
a prompt-builder function; ``gene_library`` — JSON patch of a gene record);
the rest are declared for the contract and land incrementally.
"""

from __future__ import annotations

from typing import Literal

MechanismFamily = Literal[
    "prompt_instruction",
    "gene_library",
    "signal_profile",
    "selector_policy",
    "validation_rule",
    "autopoiesis_rule",
    "feature_flag_default",
]

#: family → editable hooks (canonical map; the only source of truth).
HOOKS_BY_MECHANISM_FAMILY: dict[str, tuple[str, ...]] = {
    "prompt_instruction": ("build_gep_prompt",),
    "gene_library": ("gene_signal_alias",),
    "signal_profile": ("signal_keyword_weight", "signal_threshold"),
    "selector_policy": ("drift_intensity", "epigenetic_boost"),
    "validation_rule": ("gene_validation_cmd", "validation_timeout"),
    "autopoiesis_rule": ("viability_threshold", "homeostasis_target"),
    "feature_flag_default": ("flag_default_value",),
}

#: families implemented in this sprint (others are declared, not yet wired).
IMPLEMENTED_FAMILIES: frozenset[str] = frozenset(
    {"prompt_instruction", "gene_library"}
)


def known_family(family: str) -> bool:
    return family in HOOKS_BY_MECHANISM_FAMILY


def hook_belongs_to_family(family: str, hook: str) -> bool:
    """True iff *hook* is an editable hook of *family*."""
    return hook in HOOKS_BY_MECHANISM_FAMILY.get(family, ())


def hooks_for_family(family: str) -> tuple[str, ...]:
    return HOOKS_BY_MECHANISM_FAMILY.get(family, ())


__all__ = [
    "HOOKS_BY_MECHANISM_FAMILY",
    "IMPLEMENTED_FAMILIES",
    "MechanismFamily",
    "hook_belongs_to_family",
    "hooks_for_family",
    "known_family",
]
