"""Tests for hook taxonomy + contract validation + apply (Sprint C1)."""

from __future__ import annotations

import ast

import pytest

from evolver.gep.hooks.apply import apply_candidate_values
from evolver.gep.hooks.taxonomy import (
    HOOKS_BY_MECHANISM_FAMILY,
    hook_belongs_to_family,
    hooks_for_family,
    known_family,
)
from evolver.gep.hooks.validate import (
    MechanismContractError,
    validate_mechanism_contract,
)

_SOURCE = """\
import os


def build_gep_prompt(now_iso):
    return "old prompt"


def other():
    return 1
"""


class TestTaxonomy:
    def test_known_family(self) -> None:
        assert known_family("prompt_instruction")
        assert known_family("gene_library")
        assert not known_family("bogus")

    def test_hook_belongs(self) -> None:
        assert hook_belongs_to_family("prompt_instruction", "build_gep_prompt")
        assert not hook_belongs_to_family("prompt_instruction", "gene_signal_alias")
        assert hook_belongs_to_family("gene_library", "gene_signal_alias")

    def test_all_hooks_are_strings(self) -> None:
        for family, hooks in HOOKS_BY_MECHANISM_FAMILY.items():
            assert hooks, f"family {family} has no hooks"
            assert all(isinstance(h, str) for h in hooks)

    def test_hooks_for_family(self) -> None:
        assert hooks_for_family("selector_policy") == (
            "drift_intensity",
            "epigenetic_boost",
        )
        assert hooks_for_family("nope") == ()


class TestValidateMechanismContract:
    def test_valid_single_hook(self) -> None:
        hooks = validate_mechanism_contract(
            mechanism_family="prompt_instruction",
            candidate_values={"build_gep_prompt": "new"},
        )
        assert hooks == ["build_gep_prompt"]

    def test_unknown_family_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="unknown mechanism_family"):
            validate_mechanism_contract(mechanism_family="bogus", candidate_values={"x": 1})

    def test_empty_values_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="non-empty dict"):
            validate_mechanism_contract(mechanism_family="prompt_instruction", candidate_values={})

    def test_two_hooks_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="exactly one hook"):
            validate_mechanism_contract(
                mechanism_family="prompt_instruction",
                candidate_values={"build_gep_prompt": "a", "other": "b"},
            )

    def test_wrong_family_hook_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="does not belong"):
            validate_mechanism_contract(
                mechanism_family="gene_library",
                candidate_values={"build_gep_prompt": "x"},
            )

    def test_same_value_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="does not differ"):
            validate_mechanism_contract(
                mechanism_family="prompt_instruction",
                candidate_values={"build_gep_prompt": "same"},
                current_values={"build_gep_prompt": "same"},
            )


class TestApplyPromptInstruction:
    def test_replaces_function_body(self) -> None:
        new_body = 'def build_gep_prompt(now_iso):\n    return "new prompt"\n'
        result = apply_candidate_values(
            mechanism_family="prompt_instruction",
            candidate_values={"build_gep_prompt": new_body},
            surface=_SOURCE,
        )
        assert '"new prompt"' in result
        assert 'return "old prompt"' not in result
        assert "def other():" in result  # untouched
        ast.parse(result)  # valid python

    def test_missing_function_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="no top-level function"):
            apply_candidate_values(
                mechanism_family="prompt_instruction",
                candidate_values={"build_gep_prompt": "def build_gep_prompt(x):\n    pass\n"},
                surface="def unrelated():\n    pass\n",
            )

    def test_empty_value_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="non-empty source"):
            apply_candidate_values(
                mechanism_family="prompt_instruction",
                candidate_values={"build_gep_prompt": "   "},
                surface=_SOURCE,
            )

    def test_non_str_surface_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="Python source"):
            apply_candidate_values(
                mechanism_family="prompt_instruction",
                candidate_values={"build_gep_prompt": "def f(x):\n    pass\n"},
                surface={"not": "source"},
            )


class TestApplyGeneLibrary:
    def test_extend_signals_match(self) -> None:
        gene = {"id": "g1", "signals_match": ["error"]}
        result = apply_candidate_values(
            mechanism_family="gene_library",
            candidate_values={"gene_signal_alias": ["new_signal", "error"]},
            surface=gene,
        )
        assert result["signals_match"] == ["error", "new_signal"]  # dedup

    def test_missing_signals_match_created(self) -> None:
        gene = {"id": "g1"}
        result = apply_candidate_values(
            mechanism_family="gene_library",
            candidate_values={"gene_signal_alias": ["s1"]},
            surface=gene,
        )
        assert result["signals_match"] == ["s1"]

    def test_bad_value_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="list of signal strings"):
            apply_candidate_values(
                mechanism_family="gene_library",
                candidate_values={"gene_signal_alias": "not-a-list"},
                surface={"id": "g1"},
            )

    def test_non_dict_surface_raises(self) -> None:
        with pytest.raises(MechanismContractError, match="gene record"):
            apply_candidate_values(
                mechanism_family="gene_library",
                candidate_values={"gene_signal_alias": ["s1"]},
                surface="not-a-dict",
            )
