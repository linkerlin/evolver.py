"""Evolution pipeline stages."""

from evolver.evolve.pipeline.autopoiesis import autopoiesis_phase
from evolver.evolve.pipeline.collect import collect_phase
from evolver.evolve.pipeline.dispatch import dispatch_phase
from evolver.evolve.pipeline.enrich import enrich_phase
from evolver.evolve.pipeline.hub import hub_phase
from evolver.evolve.pipeline.select import select_phase
from evolver.evolve.pipeline.signals import signals_phase

__all__ = [
    "autopoiesis_phase",
    "collect_phase",
    "dispatch_phase",
    "enrich_phase",
    "hub_phase",
    "select_phase",
    "signals_phase",
]
