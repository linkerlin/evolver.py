# MCP Taste Polish: Faster solidify + clean status + beginner tool guidance

Date: 2026-11-01  
Status: approved (user sign-off)  
Repo: evolver.py

## Problem

MCP hosts running the evolver namespace experience three friction points after recent soft-default work:

1. **Slow soft-accept latency**: Soft-continue paths still run the full T0 acceptance suite (ruff/mypy/pytest cascade), blocking MCP tool returns for tens of seconds even when the outcome is already known to be soft. Hosts timeout or retry, creating perceived unreliability.

2. **Confusing status after success**: After a successful solidify (including soft_accept), `swarm_status` and `swarm_boot` still report `pending_solidify=true` indefinitely. Additionally, when legacy in-repo paths (`memory/evolution`, `.evolver/gep`) coexist with the new `~/.evolver/workspaces/<id>/` state_root, status gives no guidance about the dual state or how to consolidate it.

3. **Overwhelming tool surface**: First-time users face 15+ swarm tools without clarity on which form the essential loop. Advanced tools (episode_inspect, approval flows, feedback telemetry) are necessary but distract from the boot→tick→distill→hypothesis→solidify→feedback core.

These issues do not block function but degrade the perceived quality and beginner experience of the permanent soft-default UX.

## Goals

1. **Solidify speed on soft paths**: Soft-accept and soft-continue return complete MCP envelopes in seconds, not tens of seconds, by skipping or minimally probing T0 acceptance instead of running the full suite.

2. **Accurate post-solidify status**: After solidify success (any severity), `pending_solidify` must be false; status/boot must surface legacy-path coexistence with actionable next-step guidance when detected.

3. **Beginner-first tool surface**: Status and boot responses list the core loop tools and current next_action prominently; advanced tools remain callable but are not foregrounded in initial guidance.

## Non-goals

- Asynchronous background T0 jobs that complete after the MCP tool returns (introduces state/notification complexity).
- Deleting or hiding advanced MCP tools (they stay; we adjust guidance only).
- Auto-migrating legacy in-repo state to `~/.evolver` (migration is opt-in via `evolver migrate-state` or equivalent).
- Changing the hard-block policy (secrets, `~/.evolver` protected paths, `val_seal` remain hard blocks as defined in beginner-soft-default).

## Wave 1 — Solidify faster

### Changes

- **Soft-path T0 strategy**: On soft-accept or soft-continue paths (no baseline, pack absent, unmeasured, Hub offline, missing cascade tools, skipped stages, non-zero cascade exit under soft-default, etc.), skip the full T0 acceptance suite or use a minimal probe (e.g. syntax-only parse check if applicable, or skip validation entirely).
- **Hard-path unchanged**: Formal full-acceptance paths (strict mode if/when introduced, or paths where the user has explicitly requested full validation) still run the complete T0 suite.
- **Outcome recording**: Episode and return envelope record `t0_acceptance: "skipped_soft"` or similar reason string, plus any warnings from the decision to skip.
- **Experience persistence**: Gene, Capsule candidates, and episode records are still written to `~/.evolver/workspaces/<id>/` as today; `experience_written` populated normally.
- **Worktree dirty behavior**: Working-tree changes remain as the host left them (staged/unstaged unchanged), matching PR #6 behavior; no rollback on soft validation skip.

### Acceptance criteria

1. **Latency**: Soft-accept solidify (no baseline, or skipped cascade stage, or soft validation warning) returns MCP envelope in ≤5 seconds on typical hardware (no heavy subprocess blocking the response).
2. **Correctness**: Episode written with `t0_acceptance: "skipped_soft"` and appropriate warning; Gene/Capsule persisted under state_root; return `ok=true` with `severity=soft` and warnings as today.
3. **Hard path preserved**: When a hard gate or full-acceptance condition is met, T0 still runs in full (behavior unchanged for those paths).

## Wave 2 — Clean status

### Changes

- **pending_solidify false on success**: After any successful solidify (including soft_accept), clear the pending flag so `swarm_status` / `swarm_boot` no longer report stale pending state.
- **Legacy-path coexistence guidance**: When `swarm_status` or `swarm_boot` detect that both in-repo legacy paths (`memory/evolution`, `.evolver/gep`, or other pre-U-1 locations) and the new state_root `~/.evolver/workspaces/<id>/` contain evolution data:
  - Include a short `migration_notice` section in the response with: explanation that both old and new state exist, why this happened (migration to externalized state in v1.113+), and the recommended next step: `evolver migrate-state` (or MCP equivalent if one is added).
  - Do not auto-migrate; do not fail or block; just surface the notice.
- **No migration if clean**: If only state_root exists (no legacy in-repo data), or only legacy exists (pre-migration setup), no migration notice.

### Acceptance criteria

1. **pending_solidify cleared**: After solidify returns `ok=true` (any severity), subsequent `swarm_status` shows `pending_solidify: false`.
2. **Coexistence notice present**: On a workspace with both in-repo `memory/evolution/` (containing episodes or events) and state_root `~/.evolver/workspaces/<id>/evolution/` (also populated), status includes `migration_notice` with short explanation and `evolver migrate-state` next step.
3. **Coexistence notice absent**: Clean workspace (only state_root, or only legacy, or neither) has no migration notice in status/boot.

## Wave 3 — Beginner tool surface

### Changes

- **Core loop guidance in status/boot**: `swarm_status` and `swarm_boot` responses add a `beginner_guidance` or `tool_surface` section listing:
  - **Core loop tools** (the minimal set): `swarm_boot`, `swarm_tick`, `swarm_distill`, `swarm_hypothesis`, `swarm_solidify`, `swarm_feedback`, `swarm_status`.
  - **Current next_action** (already present; emphasize in this section): e.g. `tick` after boot, `distill` after host edit, `hypothesis` after distill, `solidify` after hypothesis, `feedback` after solidify, `tick` again to loop.
  - Short one-liner per core tool (purpose, not full API).
- **Advanced tools not removed**: `episode_inspect`, `swarm_approve`, `swarm_checkpoint_working`, `swarm_propose`, `swarm_hooks`, `swarm_hook_event`, `swarm_supervision`, asset read/write tools, and others remain callable and documented in MCP schema; they are simply not listed in the beginner_guidance section.
- **Instrument / boot messaging**: Update any "available tools" enumeration in instrument prompt or boot response to foreground the core loop, with a note that advanced tools are available via schema/inspection.

### Acceptance criteria

1. **Guidance present**: `swarm_status` and `swarm_boot` include a `beginner_guidance` or similar field with the seven core loop tools listed, current next_action, and brief per-tool descriptions.
2. **Advanced tools callable**: An MCP call to `episode_inspect` or another advanced tool still succeeds (not hidden/removed).
3. **Instrument alignment**: Boot or instrument strings do not list all 15+ tools flat; they mention "core loop tools" and optionally link to full schema or advanced tool list.

## Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Skipping T0 hides real errors | Soft skip only for soft reasons; hard paths unchanged; warnings recorded |
| pending_solidify clearing races with next tick | Clearing is tied to solidify success return; tick checks that state before starting new cycle |
| Migration notice spam | Only when both state locations exist and are populated; one-time per workspace after migration, then notice disappears once user migrates or cleans legacy |
| Beginner guidance brittleness | Core loop set is stable (unchanged since蜂群 introduction); list is declarative config not scattered |
| Latency still too high on some paths | Profile soft-path codepath; if minimal probe is still slow, skip validation entirely for soft and document in episode |

## Test notes

- **Wave 1**: E2E MCP test with soft-accept path (no baseline); assert latency <5s, episode has `t0_acceptance: "skipped_soft"`, worktree dirty unchanged, experience written.
- **Wave 2**: E2E with successful soft solidify → status check → `pending_solidify: false`. Separate test with dual state (seed in-repo + state_root) → status includes migration_notice.
- **Wave 3**: Parse status/boot response → assert `beginner_guidance` present with 7 core tools; separately assert `episode_inspect` MCP call succeeds (not removed).

## Implementation order

1. Wave 1 (solidify speed) first; unblocks perception of responsiveness.
2. Wave 2 (status clean-up) next; depends on solidify success state.
3. Wave 3 (tool surface) last; cosmetic guidance layer, no runtime dependencies.

Each wave is independently deployable and testable.

## Success criteria (overall)

- **Speed**: Soft-accept solidify MCP return <5s.
- **Accuracy**: `pending_solidify` false after success; migration notice only when both state locations exist.
- **Usability**: First-time MCP user sees 7 core tools + next_action in status/boot, not overwhelming 15+ flat list.
- **Compatibility**: Hard-block policy unchanged; advanced tools remain callable; no auto-migration; no breaking changes to MCP schema.

## Out of scope follow-ups

- Async T0 background validation with notification callback (introduces event/poll complexity; defer).
- Automatic legacy state migration (too invasive; keep opt-in `evolver migrate-state`).
- Per-tool progressive disclosure UI in MCP clients (client-side feature, not server responsibility).
- Further cascade probe strategies for non-Python projects (covered by beginner-soft-default; this spec only speeds existing soft paths).
