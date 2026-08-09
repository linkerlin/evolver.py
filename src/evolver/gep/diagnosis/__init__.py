"""Self-Harness causal-diagnosis layer (opt-in).

Methodology inspired by Self-Harness (arXiv:2606.09498, *Harnesses That
Improve Themselves*) — terminal-cause-first causal attribution of failed
``EvolutionEvent`` trajectories. No Node.js equivalent; this is an evolver.py
self-research addition gated behind ``EVOLVER_FF_DIAGNOSIS``.

See ``SelfHarness演进方案.md`` Sprint B1 and §4.0 integration constraints
(C-1 process boundary, C-2 ``causal_*`` naming, C-4 signal injection).
"""
