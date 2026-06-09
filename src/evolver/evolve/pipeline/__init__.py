"""Evolution pipeline stages."""

from evolver.evolve.pipeline.collect import collect_phase
from evolver.evolve.pipeline.dispatch import dispatch_phase
from evolver.evolve.pipeline.enrich import enrich_phase
from evolver.evolve.pipeline.hub import hub_phase
from evolver.evolve.pipeline.select import select_phase
from evolver.evolve.pipeline.signals import signals_phase

__all__ = [
    "collect_phase",
    "signals_phase",
    "hub_phase",
    "enrich_phase",
    "select_phase",
    "dispatch_phase",
]
