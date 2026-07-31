"""Experiment framework — controlled evolution evaluation.

Equivalent to ``evolver/src/experiment/`` (4 files).

Provides a harness for running controlled A/B experiments comparing a
baseline agent (no evolution) against an evolved agent (with gene injection)
on a set of benchmark tasks. Produces structured metrics for analysis.

Modules:
  - :mod:`agent_runner` — run a single agent on a task.
  - :mod:`metrics` — compute aggregate success/cost/latency metrics.
  - :mod:`comparison` — orchestrate a multi-configuration comparison.
  - :mod:`cli` — CLI entry point.
  - :mod:`trigger_shift` — offline trigger/context overfitting guard.
"""

from evolver.experiment.trigger_shift import (
    TRIGGER_SHIFT_AXES,
    TRIGGER_SHIFT_METHOD_VERSION,
    evaluate_trigger_shift,
    small_trigger_shift_suite,
)

__all__ = [
    "TRIGGER_SHIFT_AXES",
    "TRIGGER_SHIFT_METHOD_VERSION",
    "evaluate_trigger_shift",
    "small_trigger_shift_suite",
]
