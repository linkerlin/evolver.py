# Design: Pin MCP host workspace to evolver.py + align soft-default copy

Date: 2026-10-31  
Status: approved (chat) — awaiting user review of this file before implementation plan  
Repo: linkerlin/evolver.py

## Goal

1. **Host workspace = product repo.** MCP may still start with process cwd `/workspace`, but `repo_root` / mutation root / `workspace_id` bind to the `evolver.py` checkout (box: `/workspace/evolver-research/evolver.py`; OMEN16: `C:\GitHub\evolver.py`). Scratch `/workspace` is only the MCP launch directory, not the evolution target.
2. **Full-chain soft for usability gaps.** `solidify` and `session accept` / `publish` treat drop / flat / regression / no_baseline / pack_absent / unmeasured as soft + warnings + next_steps (experience may still be written under soft-default policy).
3. **Hard blocks only:** secrets/credentials into repo or event payloads; mutations that rewrite `~/.evolver` / engine-protected paths; `val_seal` breach.
4. **Copy matches code.** Instrument, config comments, and session messaging must not say drop/flat/regression are hard rejects.

## Non-goals

- Migrating existing scratch workspace (`c52ddf…`) Gene/Episode into the product `workspace_id` (optional later).
- Changing MCP process cwd away from `/workspace` (we keep cwd; override roots via env/config).
- Auto-commit of mutation diffs (unchanged: experience in `~/.evolver`, no auto git commit).

## Pin mechanism

- Prefer existing env if present (e.g. `EVOLVER_REPO_ROOT`); otherwise introduce/document the canonical override used by `get_repo_root` / `get_workspace_root` (or equivalent path helpers).
- When set to the product checkout, swarm status reports that path as `repo_root` / `workspace_root`, state under the matching `~/.evolver/workspaces/<id>/`, and instrument text tells the host to edit that tree only.
- Grok Bot MCP launch: keep `uv --project <evolver.py> run evolver mcp` from `/workspace`, and set the override so mutation root ≠ process cwd.
- After MCP restart: `source_revision` still tracks engine code; `repo_root` must be the product path.

## Soft gates + copy

- Update `build_instrument_prompt` (and any config/session strings) so soft-continue language covers drop/flat/regression consistently with `USABILITY_SOFT_REASONS` and soft-default solidify/publish.
- Align `session accept` / publish refusal paths with the same hard-block set as above.
- Remove leftover "drop/flat/regression 仍硬拒绝" wording.

## Tests & acceptance

- Unit tests: env override pins roots; soft reasons include drop/flat/regression for solidify and accept/publish; instrument render does not claim those are hard.
- Acceptance: MCP restarted with pin → `swarm_status.repo_root` is product checkout; boot `severity=soft` on no_baseline; instrument has no hard-reject line for drop/flat/regression; soft accept/publish path returns warnings not hard stop for those reasons.

## Success criteria

- Host evolves `evolver.py`, not `/workspace` scratch clutter.
- Beginner loop copy and gates agree: soft usability gaps, hard only secrets / `~/.evolver` / val_seal.
