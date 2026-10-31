# Beginner Soft Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make evolver permanently soft-default so a first swarm loop always completes with visible experience under `~/.evolver`, without forcing `src/` or auto-committing the user repo; hard-block only secrets and protected state paths.

**Architecture:** Add a layout-aware validation probe that rewrites or skips fitness-cascade stages; map former hard validation/acceptance failures to soft warnings that still persist Gene/Episode; keep git commit off the default solidify path; surface `experience_written` on MCP payloads. Comprehensive unit tests cover probe, soft mapping, hard blocks, no-commit, and no-src e2e.

**Tech Stack:** Python 3, pytest, existing `evolver.gep.solidify` / `evolver.ops.open_box` / `evolver.swarm` MCP layer.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-31-beginner-soft-default-design.md` (approved).
- Hard blocks only: secrets; mutation targeting `~/.evolver` / state_root / `do_not_touch`.
- Soft: missing baseline/pack, Hub offline, absent paths, skipped/failed ruff/mypy/pytest, unmeasured, drop/flat/regression, no git root (still write experience + warn).
- No auto `git commit` on solidify success.
- Experience only under `get_evolver_state_root()` / workspace state dir.
- Never instruct hosts to create `src/`.
- Unit test coverage must be comprehensive for every new behavior; keep existing suites green.
- Prefer small commits; TDD per task.

---

## File map

| Path | Role |
| --- | --- |
| `src/evolver/gep/validation_probe.py` (create) | Discover check roots; adapt/skip cascade commands |
| `src/evolver/config.py` | Keep cascade templates; document they are templates not fixed paths |
| `src/evolver/gep/solidify.py` | Use probe; soft validation failures; no default commit; `experience_written` |
| `src/evolver/ops/open_box.py` | Expand soft taxonomy helpers if needed |
| `src/evolver/swarm.py` | Instrument + MCP fields (`experience_written`, soft wording) |
| `tests/gep/test_validation_probe.py` (create) | Probe unit tests |
| `tests/gep/test_solidify_soft_default.py` (create) | Soft solidify / no-commit / hard-block |
| `tests/swarm/test_soft_default_mcp.py` or extend existing swarm MCP tests | Payload fields |
| Usability e2e under existing soft-continue e2e paths | no-src loop |

---

### Task 1: Validation probe

**Files:**
- Create: `src/evolver/gep/validation_probe.py`
- Create: `tests/gep/test_validation_probe.py`
- Modify: `src/evolver/gep/solidify.py` (`get_fitness_cascade_commands` callers)

**Interfaces:**
- Produces: `discover_check_roots(cwd: Path) -> list[str]`
- Produces: `adapt_cascade_commands(commands: list[dict], cwd: Path) -> tuple[list[dict], list[str]]`  
  (runnable specs, skip_warnings)

- [ ] **Step 1: Failing tests** for: empty cwd → skip all with warnings; `src/`+`tests/` present → keep/adapt; only `lib/` → rewrite `src` arg to `lib`; tool missing already handled upstream — probe focuses on paths; never invent `src` dir on disk.

- [ ] **Step 2: Implement probe** (pure functions, no mkdir).

- [ ] **Step 3: Wire** `get_fitness_cascade_commands` / solidify validation prep to call `adapt_cascade_commands`.

- [ ] **Step 4: pytest** `tests/gep/test_validation_probe.py -q` PASS; commit.

---

### Task 2: Soft validation policy in solidify

**Files:**
- Modify: `src/evolver/gep/solidify.py` (validation failure → soft continue + warnings; no worktree rollback for soft validation)
- Create/extend: `tests/gep/test_solidify_soft_default.py`

**Interfaces:**
- Consumes: adapted cascade from Task 1
- Produces: solidify result with `ok=True`, `severity="soft"`, `warnings` when validation soft-fails; still writes experience

- [ ] **Step 1: Tests** — intentional failing command → `ok is True`, warnings non-empty, worktree file from mutation still present, Gene/Episode or event written under state_root env.
- [ ] **Step 2: Tests** — empty cascade (all skipped) → `ok is True` + skip warnings.
- [ ] **Step 3: Implement** soft path; ensure hard secrets / protected-path still rollback + `ok=False`.
- [ ] **Step 4: pytest** focused + related solidify fitness tests; commit.

---

### Task 3: Soft acceptance outcomes (drop/flat/regression/unmeasured)

**Files:**
- Modify: acceptance / solidify gate mapping (wherever drop/flat/regression hard-reject today — likely `solidify.py` + acceptance hook)
- Extend: `tests/gep/test_solidify_soft_default.py`

- [ ] **Step 1: Tests** for each former hard outcome → soft warn, experience written, no rollback (except secrets/protected).
- [ ] **Step 2: Implement** mapping; do not write Parent baseline on soft-accept.
- [ ] **Step 3: pytest**; commit.

---

### Task 4: No auto-commit + no-git experience

**Files:**
- Modify: solidify success path that currently commits (if any)
- Extend tests

- [ ] **Step 1: Test** successful soft solidify does not create a new git commit (compare `rev-parse HEAD` before/after).
- [ ] **Step 2: Test** cwd without `.git` still writes experience to state_root with soft warning.
- [ ] **Step 3: Implement**; commit.

---

### Task 5: MCP / instrument / doctor surfaces

**Files:**
- Modify: `src/evolver/swarm.py`, MCP docs strings, doctor exit policy if still hard on soft gaps
- Tests: swarm/MCP status payload includes `experience_written` after success

- [ ] **Step 1: Tests** for `experience_written` shape `{genes: [...], episodes: [...], events: [...]}` (ids).
- [ ] **Step 2: Remove** instrument language that requires creating `src/`.
- [ ] **Step 3: pytest**; commit.

---

### Task 6: Comprehensive regression + usability e2e

**Files:**
- Extend existing soft-continue / usability e2e
- Add no-src toy repo fixture loop test

- [ ] **Step 1:** e2e no-src: boot→tick (or solidify-focused harness) asserts ok + experience + no src created by engine.
- [ ] **Step 2:** Run broad suites: `pytest tests/gep/test_validation_probe.py tests/gep/test_solidify_soft_default.py tests/gep/test_solidify_fitness.py tests/gep/test_solidify_bench_pack.py` plus swarm MCP / open_box doctor soft tests — all green.
- [ ] **Step 3:** Document behavior briefly in quickstart if present; commit; open PR to master.

---

## Spec coverage checklist

- [x] Permanent soft default → Tasks 2–3
- [x] Hard blocks secrets/state_root → Task 2
- [x] Probe / no forced src → Task 1, 6
- [x] Experience in ~/.evolver → Tasks 2–4
- [x] No auto commit → Task 4
- [x] Visible Gene/Episode success → Tasks 2, 5, 6
- [x] MCP fields / instrument → Task 5
- [x] Comprehensive unit tests → every task

## Out of scope

- Opt-in strict profile
- Shadow worktree
- Hub connectivity fixes
