## Summary

Short 1-2 sentence summary of the change.

## What changed

- Bullet list of changes

## How to test

1. Copy commands
2. Expected output

## Risk

Low / Medium / High -- note if it touches infra or public API.

## Harness/evaluator governance

Required when this PR touches Evolver harness/evaluator/self-evolution surfaces:
GEP schemas, prompt/selector/mutation/solidify/candidate/evaluator logic,
evolve pipeline, adapter execution bridge, proxy routing/trace, bundled GEP
assets, or the EvoX bridge contract. For unrelated PRs, write
`N/A -- not a harness/evaluator governance change` on each line.

Upstream governance surface: <typed Evolver surface, or N/A>
Downstream EvoX impact: <bridge/contract/runtime impact, or N/A>
Rollout-local scope: <proposal/shadow/cohort boundary before promotion, or N/A>
Promotion boundary: <proposal→rollout→PR/default boundary, or N/A>
Evaluator mismatch sets: <observation/action/repair/verification/evidence/belief sets covered, or N/A>
Non-regression evidence: <tests/shadow runs/replay/doc-only rationale, or N/A>
Fix-severity review: <low | medium | high | critical>
Owner approval: <owning module/reviewer requirement, or N/A>
Security boundary: <data/tool/host/network/secrets impact, or N/A>
Rollback: <disable/revert/quarantine path, or N/A>
Live promotion: no
Autonomous evaluator self-editing: no

## Self-check

Tick only the boxes that apply, but every applicable box must be ticked.

- [ ] New source files import from `.py` source in CI (D7 import smoke —
      `tests/test_import_smoke.py` covers the key modules; add new critical
      modules to its list).
- [ ] If this PR adds or modifies a Pydantic schema factory under
      `src/evolver/gep/schemas/`, the corresponding `validate*` function is
      invoked at every write and every publish call site (not just defined).
- [ ] If this PR copies an object with mutable fields (arrays, sub-objects),
      reference-typed fields are sliced/cloned — never held by reference to
      the source.
- [ ] If this PR reads a new environment variable at module level, the
      owning module is imported lazily (after `cli.py:_load_dotenv()`) or the
      value goes through `evolver.config` — see AGENTS.md 坑阱篇 (.env load
      order).
- [ ] No new runtime dependencies without a clear justification in "What
      changed".
- [ ] Tests added or updated to cover the new behavior; gates pass locally:
      `uv run pytest`, `uv run ruff check src tests`,
      `uv run ruff format --check src tests`, `uv run mypy src`.

## Related

Closes #NN
