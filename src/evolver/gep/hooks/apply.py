"""Apply constrained candidate values to the editable surface.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``hooks.py`` ``apply_candidate_values``). No Node.js equivalent; evolver.py
self-research addition (Sprint C1).

Two edit kinds, both operating on plain inputs (testable, no I/O):

* **prompt_instruction** hooks edit a Python source file's function body
  (AST span replacement via :mod:`evolver.gep.hooks.ast_merge`);
* **gene_library** hooks patch a gene record dict in place.

``apply_candidate_values`` is the single entry point: it validates the
mechanism contract first, then dispatches to the family implementation.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.hooks.ast_merge import (
    top_level_function_spans,
)
from evolver.gep.hooks.validate import (
    MechanismContractError,
    validate_mechanism_contract,
)


def _replace_function_body(source: str, func_name: str, new_body: str) -> str:
    """Replace the body of top-level function *func_name* in *source*.

    The replacement is the full function source (def line + decorators +
    body). Raises :class:`MechanismContractError` when the function does not
    exist.
    """
    spans = top_level_function_spans(source)
    if func_name not in spans:
        raise MechanismContractError(
            f"surface has no top-level function {func_name!r}"
        )
    start, end = spans[func_name]
    lines = source.splitlines()
    lines[start - 1 : end] = new_body.splitlines()
    return "\n".join(lines)


def _apply_prompt_instruction(
    source: str, hook: str, value: Any
) -> str:
    """Rewrite a prompt-builder function body (hook → function name)."""
    if not isinstance(value, str) or not value.strip():
        raise MechanismContractError(
            f"prompt_instruction hook {hook!r} requires non-empty source"
        )
    return _replace_function_body(source, hook, value)


def _apply_gene_library(gene: dict[str, Any], hook: str, value: Any) -> dict[str, Any]:
    """Patch a gene record (hook ``gene_signal_alias`` → extend signals_match)."""
    if hook != "gene_signal_alias":
        raise MechanismContractError(f"unimplemented gene_library hook {hook!r}")
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise MechanismContractError(
            "gene_signal_alias requires a list of signal strings"
        )
    signals = list(gene.get("signals_match") or [])
    for sig in value:
        if sig not in signals:
            signals.append(sig)
    gene["signals_match"] = signals
    return gene


def apply_candidate_values(
    *,
    mechanism_family: str,
    candidate_values: dict[str, Any],
    surface: Any,
    current_values: dict[str, Any] | None = None,
) -> Any:
    """Apply *candidate_values* (exactly one hook) to *surface*.

    *surface* is the family's editable object: a Python source ``str`` for
    ``prompt_instruction``, a gene record ``dict`` for ``gene_library``.
    Returns the edited surface (new str / mutated dict).
    """
    hooks = validate_mechanism_contract(
        mechanism_family=mechanism_family,
        candidate_values=candidate_values,
        current_values=current_values,
    )
    hook = hooks[0]
    value = candidate_values[hook]

    if mechanism_family == "prompt_instruction":
        if not isinstance(surface, str):
            raise MechanismContractError(
                "prompt_instruction surface must be Python source (str)"
            )
        return _apply_prompt_instruction(surface, hook, value)
    if mechanism_family == "gene_library":
        if not isinstance(surface, dict):
            raise MechanismContractError(
                "gene_library surface must be a gene record (dict)"
            )
        return _apply_gene_library(surface, hook, value)
    raise MechanismContractError(
        f"mechanism_family {mechanism_family!r} not yet implemented"
    )


__all__ = ["apply_candidate_values"]
