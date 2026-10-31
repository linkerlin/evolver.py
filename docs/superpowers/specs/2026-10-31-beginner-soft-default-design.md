# Beginner-first permanent soft default

Date: 2026-10-31  
Status: approved (Halo Master)  
Repo: evolver.py

## Problem

A new user (or an MCP host) should finish **one visible evolution loop** quickly. Today they stall on environment and layout gates: missing Parent baseline, missing freeze pack, Hub offline, and especially the hard-coded fitness cascade `ruff check src tests` / `mypy src` when the project has no `src/`. Soft-continue already softens pack/baseline/unmeasured, but solidify validation and several acceptance outcomes still hard-fail or roll back the worktree. Experience already lives under `~/.evolver/`, yet the product still behaves as if the user's cwd must look like evolver's own Python package layout.

## Goals

1. **First-loop success**: `swarm_boot → swarm_tick → host edit → swarm_distill → swarm_hypothesis → swarm_solidify` returns `ok=true` and leaves **visible experience** (Gene and/or Episode) under `~/.evolver/workspaces/<id>/`, readable via `swarm_status` / asset tools.
2. **Permanent soft default** (not a temporary beginner mode): almost all gates warn and continue.
3. **No forced layout**: never require `src/` or any other fixed tree shape.
4. **State outside cwd**: Genes, Capsules, episodes, events, hypothesis scratch live under `~/.evolver` (honoring `EVOLVER_STATE_ROOT`). Do not auto-commit the user's repo.

## Non-goals

- Shadow worktrees that keep the user's cwd read-only (rejected route C).
- A separate "beginner mode" flag as the primary product story (rejected route A); behavior is the global default.
- Solving val / opening sealed val materials in the candidate chat.
- Auto `git commit` / `session accept` / publish without an explicit human step later.

## Decisions (from design review)

| Topic | Choice |
| --- | --- |
| Softness | Almost all soft; only security hard-blocks |
| Commit | Experience → `~/.evolver`; code stays uncommitted |
| Validation | Probe layout; missing tool/path → skip + warning (not failure) |
| Success bar | Closed loop **and** visible Gene/Episode |
| Product route | **B** permanent soft default |

## Hard blocks (only)

Solidify / host mutation **must refuse and roll back** only when:

1. **Secrets**: credentials or secret material would be written into the repo or event payloads (existing secrets policy).
2. **Protected state**: mutation targets `~/.evolver`, `EVOLVER_STATE_ROOT`, workspace state_root, or other engine-owned paths listed in `do_not_touch`.

Everything else is soft: missing baseline/pack, Hub offline, absent `src/`, skipped or failed ruff/mypy/pytest, unmeasured val, drop/flat/regression signals, doctor soft gaps.

## Soft outcomes

For soft conditions:

- Return `ok=true` (or continue the loop) with `severity=soft`.
- Populate `warning` / `warnings`, `gap` when applicable, and `next_steps` / `commands` as recommendations—not blockers.
- **Do not** invent a Parent baseline; soft-accept must not write Parent bar.
- **Do not** auto-rollback the user's worktree for soft validation or soft acceptance failures (change from today's hard rollback on those paths). Hard-block paths still roll back.
- Always attempt to **write experience** (Gene/Capsule candidates already distilled, episode/event rows) into state_root so the loop "counts."

## Validation probe (replaces hard-coded `src`)

Default `FITNESS_CASCADE_COMMANDS` must not assume `src/`.

Before running cascade stages:

1. **Discover check roots** from the project: existing `src/`, `lib/`, package dirs declared by packaging config, or other conventional roots; for non-Python, prefer project-declared lint/test scripts if present.
2. **Rewrite or select** cascade argv to those roots when tools exist on PATH (including interpreter-local bin, as today).
3. If a tool is missing **or** no suitable path exists for that stage → **skip stage** with a warning; do not fail the cascade.
4. If a stage runs and exits non-zero → record soft warning + metrics; **do not** fail solidify under the permanent soft default.
5. Instrument / dispatch prompts must **not** tell the host to create `src/` to satisfy the engine.

Empty cascade (nothing runnable) is a valid soft path: solidify still persists experience with warnings.

## Git and publish

- Solidify **does not** create a git commit in the user repo by default.
- Working tree changes remain as the host left them (staged/unstaged unchanged by a successful soft solidify).
- Optional later human path: `evolver session accept` (or equivalent) for publish; soft-accept warnings stay until a real baseline exists.
- **No git root:** recommended but not a hard block for experience. If cwd is not a git repo, solidify still writes Gene/Episode/events to state_root, returns `ok=true` with `severity=soft` and warnings/next_steps (`git init` or set `EVOLVER_REPO_ROOT`). Diff/rollback features that require git are skipped with warnings. Secrets and protected-path hard blocks still apply.

## MCP / CLI surface

- `swarm_boot`, `swarm_status`, `swarm_solidify` always expose: `severity`, `warnings`, `source_revision`, and **`experience_written`** (ids of new Gene/Episode/event when any).
- Instrument text: emphasize closing the loop; experience lives under `~/.evolver`; layout is the user's own.
- `evolver doctor`: soft gaps → exit 0 with `[SOFT-CONTINUE]` / warnings; non-zero only for hard blocks (secrets tooling failures that leave the tree unsafe, or inability to write state_root).

## State layout (unchanged ownership, clarified product)

- `get_evolver_state_root()` → default `~/.evolver` (`EVOLVER_STATE_ROOT` override).
- Per-workspace: `~/.evolver/workspaces/<workspace_id>/` for evolution, gep assets, logs.
- Cwd `.evolver/` / `memory/evolution` = legacy; migrate/read-only hints only; hosts must not treat cwd as the experience store.

## Acceptance tests (product)

1. **No-src Python toy repo**: boot→tick→minimal edit→distill→hypothesis→solidify → `ok=true`, soft warnings about skipped/adapted cascade, Gene or Episode visible in state_root; no `src/` created by the engine; no auto commit.
2. **Missing baseline**: same loop `ok=true`, `severity=soft`, no Parent bar written.
3. **Ruff/pytest failure**: with tools present and intentional failing test, solidify still `ok=true` + warnings; experience written; worktree not rolled back for that failure.
4. **Hard block**: mutation touching state_root or injecting secrets → refuse, rollback, `ok=false`.
5. **Status**: after success, `experience_written` / gene count reflects the new asset.

## Implementation sketch (not a plan)

- Probe helper for cascade roots; soft-fail policy in solidify validation and acceptance gate mapping.
- Expand `SOFT_GAP_ERRORS` / apply soft path to former hard acceptance outcomes except secrets + protected paths.
- Stop default commit; ensure distill/solidify persistence paths only under state_root.
- Update instrument strings and quickstart; e2e usability tests for no-src + soft validation.
- Keep `source_revision` / mailbox hello ack from 40b04e7.

## Out of scope follow-ups

- Opt-in "strict" profile for power users who want hard lint/test/regression again.
- Full non-Python cascade catalogs beyond "skip or project script."
- Hub online UX (Hub offline stays soft warning only).
