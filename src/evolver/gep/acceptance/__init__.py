"""Self-Harness acceptance-gate layer (opt-in).

Methodology inspired by Self-Harness (arXiv:2606.09498, *Harnesses That
Improve Themselves*) — empirical held-in / held-out regression gating with
repeats. No Node.js equivalent; this is an evolver.py self-research addition
gated behind ``enable_acceptance_gate``.

See ``SelfHarness演进方案.md`` Sprint A1 and §4.0 / §8.7. The gate runs in
the ``solidify`` process and reads diagnosis artifacts across the process
boundary via ``last_run.diagnosis_ref`` (constraint C-1).

This subpackage implements the three held-out tiers (T0 frozen regression
snapshot / T1 semantic-temporal / T2 LLM-synthesized). T1/T2 land with
Sprint B2/B1 wiring; T0 alone is a complete regression floor.
"""
