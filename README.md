# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**English** · [简体中文](README.zh.md) · [日本語](README.ja-JP.md) · [한국어](README.ko-KR.md)

**A GEP-Powered Self-Evolution Engine for AI Agents.**

---

## 📖 Overview: Toward Compounding Agent Evolution

In standard Large Language Model (LLM) software engineering, developer agents typically suffer from a critical limitation: **stateless single-turn reasoning, inability to compound successful engineering strategies, and a lack of rigorous evolutionary criteria**. While modern AI coding assistants can generate patches, they do not autonomously harvest past successes, fix recurring friction points, or systematically improve their own mutation strategies over long horizons without human intervention.

**`evolver.py` was built to overcome this plateau.**

`evolver.py` is an autonomous agent self-evolution engine driven by the **Genome Evolution Protocol (GEP)**. It establishes an active, closed-loop evolutionary lifecycle: extracting friction signals from repositories and runtime diagnostics, matching and dispatching specialized mutation strategies, steering external host agents to perform code transformations, and verifying changes through rigorous evaluation gates and controlled ablation experiments. Verified breakthroughs are persisted as reusable **Genes** and **Capsules**.

### Core Architectural Principles

1. **Engine Decoupled from LLM Scheduling: The Host Agent is the Executor**  
   `evolver.py` does not run its own proprietary LLM inference scheduler. Instead, it leverages standard **MCP (Model Context Protocol) stdio** to take over connected host agents (e.g., Cursor, Claude Code, Codex, ZCode) as evolutionary executors. The host's native tools and workspace context act as the scalpel, while `evolver.py` serves as the cognitive brain, orchestrating signal extraction, policy selection, and safety gating.

2. **Experience as Evidence & Recursive Harness Engineering**  
   Drawing from modern autonomous research protocols (*arXiv:2609.37968v2, SelfSearch*; *arXiv:2610.14224v1, Harness2*), the engine treats an agent's runtime execution record (**Episode Record**) as a first-class source of evidence, augmented by mechanical component attribution, cross-round behavioral contrast, and selective multi-proposal composition. Rather than mutating blindly or relying on uncalibrated LLM self-scoring, every strategy promotion is backed by controlled ablation tests, pre-rollout integrity gates, and statistical sample-size sufficiency audits (verified at stage exit across 30 real MCP settlements and 32 frozen paired tasks: `p = 1.86e-09` / `2.98e-08`).

3. **Modern Clean-Room Python Implementation**  
   Developed as an independent, clean-room, behaviorally equivalent implementation of `@evomap/evolver`, `evolver.py` is built from public protocol specifications and test contracts. It leverages a modern Python stack (Python 3.12+, `asyncio`, `uv`, `Pydantic v2`, `httpx`, and optional `FastAPI`) and is released under the permissive **Apache-2.0** license.

---

## 🏛️ Architecture & Closed-Loop Lifecycle

The inner workings of `evolver.py` revolve around a 7-stage asynchronous pipeline, structured GEP data models, and a defense-in-depth safety system.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      evolver.py Evolutionary Cycle                     │
└────────────────────────────────────────────────────────────────────────┘

  [ Runtime Logs / Repo Telemetry / Test Failures ]
                         │
                         ▼
             ┌───────────────────────┐
             │   1. Collect          │ ── Scans diagnostic traces & Living Memory
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   2. Signals          │ ── Classifies signals (errors, bottlenecks)
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   3. Hub Sync         │ ── Queries remote candidate assets & tasks
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   4. Enrich           │ ── Bridges memory graph & failure-side evidence
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   5. Autopoiesis      │ ── Assesses viability & encodes friction rules
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   6. Select           │ ── Epigenetic selection with repair-bias
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   7. Dispatch         │ ── Builds GEP prompt with contextual evidence
             └───────────┬───────────┘
                         │
                         ▼  (via MCP stdio channel)
             ┌───────────────────────┐
             │ Host Agent (Executor) │ ── Cursor / Claude Code edits codebase
             └───────────┬───────────┘
                         │
                         ▼
             ┌───────────────────────┐
             │ Hypothesis & Gate     │ ── Declares single hypothesis ➔ validation suite
             └───────────┬───────────┘
                         │
        [ promote / draft_preserved / soft-accept (gaps only) ]
                         │
                         ▼
             ┌───────────────────────┐
             │ Solidify & Retain     │ ── Experience under ~/.evolver/…
             └───────────────────────┘     (no auto git commit)
```

### 1. Seven-Stage Evolution Pipeline

Every evolution cycle proceeds through seven decoupled asynchronous phases:
- **Collect**: Scans local run logs, inspects failures, and reads the `LESSONS_LEARNED.md` living memory organ.
- **Signals**: Extracts structured signals (e.g., `log_error`, `perf_bottleneck`, environment dependency drift), ranks them by problem value with WFQ anti-starvation scheduling, and scales exploration depth by idle-scheduler intensity (`signal_only`, `standard`, `deep`).
- **Hub**: Interacts with local or remote Hub networks to discover relevant prior strategies and tasks.
- **Enrich**: Bi-directionally synchronizes with the memory graph, assembling past interventions and lessons.
- **Autopoiesis**: Maintains system homeostasis by automatically turning recurring engineering friction into protective guard rules.
- **Select**: Evaluates epigenetic affinities, automatically cooling down prior `hurt`-attributed genes and pivoting to repair bias when regressions occur.
- **Dispatch**: Assembles and writes the structured GEP mutation prompt, awaiting host execution.

### 2. The GEP Asset Model

- **Gene**: An abstract, reusable mutation strategy defining which code interventions (`execution_trace`) to apply given specific signal conditions (`signals_match`).
- **Capsule**: A concrete execution record capturing inputs, generated diffs, and outcomes (success or failure).
- **Epigenetics**: Dynamic suppression or activation of genes based on recent environmental outcomes to prevent cyclical oscillation.
- **Gene Lifecycle Governance**: Tracks gene states (`active`, `under_review`, `retired`). Inert or regressive genes are automatically degraded and prevented from polluting the candidate pool.

### 3. Dual Safety Architecture (HITL + HOTL)

Because code self-modification requires strict boundaries, `evolver.py` provides layered safety rails:
- **HITL (Human-In-The-Loop Approval Gate)**: High-risk operations (such as solidifying unverified mutations) are blocked until explicitly approved by an operator. Includes global audit logging and fail-safe TTL timeouts.
- **HOTL (Human-On-The-Loop Supervision)**: Provides operators real-time oversight. Allows operators to pause/resume the loop, veto specific genes or subjects, and inject steering directives. Tripwires automatically pause evolution after consecutive degraded cycles.

---

## ⚡ Key Capabilities

### 🐝 MCP Swarm Evolution (Host Takeover)
Through a standardized stdio MCP interface, host editors do not just run tools—they become active executors inside the evolution loop. The engine generates decisions and validation constraints, while the host performs targeted mutations. Tools are annotated with `readOnlyHint` and `destructiveHint` to ensure safe, unattended autonomy.

### 🌉 Skill Ecosystem Bridge
Leverages community-wide agent capabilities out of the box. Automatically scans standard `SKILL.md` documents across **Project > User > Builtin** priority tiers, distilling them into GEP genes that immediately participate in signal matching and mutation dispatch.

### 📋 Persistent Workflow Engine (Collaboration as Data)
Express complex engineering workflows as versionable, declarative YAML files. Workflows support `agent` role steps, `gate` validation cascades (e.g., ruff ➔ mypy ➔ pytest), and `approval` human-in-the-loop checkpoints. Driven by a Write-Ahead Log (WAL) and state snapshots, interrupted runs resume cleanly.

### 🔬 Controlled Ablation Suite & Scientific Benchmarks
Guarantees verified progress over artificial gains:
- **Placebo Control Arm (`--placebo`)**: Injects neutral context of equivalent length to eliminate system prompt bias.
- **Stage Exit Contract (`--stage-exit`)**: Requires real episodes, placebo comparison, fixed commits, and written reports before declaring progress. Enforces sample size audits (`MIN_N=30`), marking low-sample conclusions as `indicative only`.
- **Repository Pinning**: Static whitelist auditing prevents mutation logic from modifying its own benchmark scoring harness.

### 🧩 Recursive Harness Engineering & Selective Composition (Harness2)
Incorporates mechanical verification and contrastive synthesis inspired by *Harness2* (*arXiv:2610.14224v1*) without adding online LLM judge overhead:
- **Four-Way Component Attribution (`H2-1`) & Cross-Round Behavioral Contrast (`H2-5`)**: Automatically classifies each round's edits as `helped | hurt | no_observed_effect | confounded` and computes check-level transitions (`newly_passed`, `regressed`, `persistent_failures`), injecting `[attribution]` and `[contrast]` notes into dispatch prompts while blocking `confounded` multi-component rounds from polluting durable gene libraries.
- **Transferable Experience Triad & Workspace-Fact Isolation (`H2-2`)**: Enforces `cue + lesson + evidence` completeness (`--strict-transferable`) for durable genes, while isolating workspace-local tactical facts (`in this workspace:`) to `WORKING_SESSION.md` (automatically archived and unlinked at session termination).
- **`INV × DOM` Orthogonal Scopes & Selective Composer (`H2-3`)**: Separates invariant/verifier (`INV`) from domain (`DOM`) proposals, mechanically merging non-conflicting `helped` edits (`compose_proposals`) or falling back to `KEEP_BASE`, and surfaces salvageable single-component semantic variants (`evolver variants`).
- **Component Cost Hierarchy Gate (`H2-4`) & Library Provenance (`H2-6`)**: Enforces `Skill > Script > Subagent > Hook > Always-On Text` pre-rollout static checks (`validate_harness_component_integrity`), 6-axis deliverable conformance, paired $\mathcal{H}_0 + \mathcal{R}_t$ library solves, and `direct_copy / adapted / novel` provenance telemetry in `evolver meta-report`.

---

## 🚀 Quick Start

### Prerequisites

- **Python >= 3.12**
- **[Git](https://git-scm.com/)** (Required: used for blast radius calculation, staging, and atomic rollbacks)
- **[uv](https://docs.astral.sh/uv/)** (Recommended modern Python packaging tool)

```bash
# Clone the repository and install dependencies
git clone https://github.com/linkerlin/evolver.py.git
cd evolver.py
uv sync
```

### Zero-Touch 3-Verb Autopilot (`init` / `up` / `status`)

In any Python repository, three zero-jargon commands cover onboarding, continuous evolution, and plain-language observability:

```bash
# 1. One-command zero-pollution onboarding (< 3s):
#    Detects installed IDEs (Claude Code, Cursor, Codex, OpenCode, ZCode),
#    idempotently wires MCP + hooks, records IDE configs in .git/info/exclude
#    (zero git status dirt), and spawns a clean background subprocess to
#    establish the native baseline & out-of-tree Anchor.
uv run evolver init

# 2. Plain-language status lamp (ready lamp, promoted fixes, saved validation
#    seconds, vault operators, and preserved workbench drafts — zero internal flags)
uv run evolver status

# 3. Start zero-touch autopilot daemon (adaptive sliding sessions + 3-round dormancy)
uv run evolver up          # pass --once for a single autopilot cycle
```

Expert and granular lifecycle commands remain available directly or under `evolver internal <subcmd>`:

```bash
uv run evolver run         # Run a single evolution cycle
uv run evolver --loop      # Run standard daemon loop
uv run evolver --review    # Pause for human review before solidifying
uv run evolver check       # Check system health
```

### Diagnostic Open-Box (`setup` / `doctor`)

The loop starts even when the frozen pack or Parent baseline is missing. Those first-run gaps are soft warnings. Run the read-only or safe-fix diagnostics anytime:

```bash
uv run evolver doctor          # git, freeze pack, Parent baseline, user lock
uv run evolver doctor --fix    # installs the freeze pack; measures a baseline only if val sandboxes are already filled
uv run evolver setup           # same as `doctor --fix`
```

Exit code `0` means you may continue (`soft_continue`), including when only the pack or baseline is missing. Exit code `2` means a hard blocker (the directory is not a git repo, or a user lock is held). `loop_ready` stays honest: it is true only when git, the pack, and the Parent baseline are all present. `--fix` never invents val answers and never opens sealed val material in the candidate chat.

Runtime state lives outside the source tree, under `~/.evolver/workspaces/<id>/` (`<id>` is `sha256(realpath(repo))[:16]`, indexed by a WAL-mode `index.sqlite` read ledger). Low-frequency runtime knobs are consolidated under `~/.evolver/config.json` (or `EVOLVER_CONFIG`). If a checkout still has legacy in-repo files (`memory/`, `.evolver/gep/`), move them:

```bash
uv run evolver migrate-state
```

`evolve_status` reports `state_root`, `workspace_id`, `saved_validation_seconds`, and `state_health.legacy_in_repo` (including `migrate_command`).

> **Optional Services**: To enable the visual WebUI dashboard or the local A2A proxy, install the `server` extra:
> ```bash
> uv sync --extra server
> uv run evolver webui   # Opens dashboard at http://127.0.0.1:8080
> uv run evolver proxy   # Starts local A2A proxy on port 8081
> ```

---

## 🛠️ Connecting Your Host Agent (MCP Configuration)

Run `uv run evolver init` inside your target project to auto-wire MCP and session hooks with zero manual JSON editing. You can also configure MCP manually if preferred.

### 1. MCP Configuration Examples

For **Cursor** (`.cursor/mcp.json`) and **Claude Code** (`.mcp.json`):

```json
{
  "mcpServers": {
    "evolver": {
      "command": "uv",
      "args": ["--project", "/absolute/path/to/evolver.py", "run", "evolver", "mcp"]
    }
  }
}
```

For **ZCode** or direct virtualenv execution:

```json
{
  "mcpServers": {
    "evolver": {
      "command": "/absolute/path/to/evolver.py/.venv/bin/python",
      "args": ["-m", "evolver.mcp_server"]
    }
  }
}
```

After `uv sync`, a pull, or an upgrade, **restart the MCP server** so the stdio process reloads updated modules (`evolve_status.source_revision` reports the running git SHA). On Grok Bot, point `EVOLVER_REPO_ROOT` at `/workspace/evolver-research/evolver.py` (see [`examples/swarm-quickstart/README.md`](examples/swarm-quickstart/README.md)).

### 2. Dynamic FSM 3-Tool Host Protocol

`evolver.py` exposes a zero-cognitive-load **Finite-State Machine (FSM) 3-tool MCP catalog** over `notifications/tools/list_changed`, eliminating multi-step ceremonial tool chains and boolean flag soup:

- **`IDLE` State** (no round in flight — exposes `evolve_begin` + `evolve_status`; `run_lens` and `evolve_settle` are hidden):
  1. `evolve_status`: Read-only health, FSM state, vault counts, active signals, and cumulative `saved_validation_seconds`.
  2. `evolve_begin`:
     - Called **without** `hypothesis` (`hypothesis=""`): runs a zero-side-effect signal & operator preview (`discovery_only=true`) and stays in `IDLE`.
     - Called **with** a plain-sentence falsifiable `hypothesis` (and optional `target_files`): locks the round's single hypothesis up front, lazily bootstraps any uninitialized workspace in a clean background subprocess, packs a high-SNR `< 4,000 tokens` GEP prompt by utility density (`utility / token_cost`), starts the in-band flight recorder, and pushes `notifications/tools/list_changed` to transition into `ACTIVE_RUN`.
- **`ACTIVE_RUN` State** (`evolve_begin` is hidden so hosts cannot double-start; exposes `run_lens` + `evolve_settle` + `evolve_status`):
  3. `run_lens` *(read-only)*: Executes deterministic Python AST and dependency lenses (`ast_hotspot`, `import_impact`, `trace_locator`, `contract_surface`) with automatic `val_seal` output redaction.
  4. *(Host edits workspace code using its native editor tools)*
  5. `evolve_settle`: Runs **`< 3s` L0 AST reverse-dependency lightning validation** (changed-file `ruff` + transitive reverse-import `pytest` targets via `gep/import_graph.py`, escalating to full L2 only on high-risk surfaces), closes the in-band cycle-boundary **blackbox** (`ast_delta`, lens call stack, diff stats, wall-clock ms — 100% engine-recorded without requiring a local HTTP proxy), records the content-addressed `episode_record`, syncs `index.sqlite`, and transitions back to `IDLE`.

Read-only auxiliary tools (`episode_get`, `episode_inspect` for val-sealed line-window zoom on truncated check output, `tool_asset_search`, `tool_asset_get`, and `tool_cycle_timeline`) remain available across both states. When promoted to the vault, an asynchronous background `eval_worktree` **L1 guardian** verifies subpackage `mypy` and broader regressions, automatically demoting regressing operators to `under_review`.

#### Dual-Track Settlement: Workbench Drafts vs. Vault Promotion (v1.114.0)

- **Promoted (`ok=true`, `outcome="promoted"`)**: All validation checks pass and net fitness improves. Experience and operators settle under `~/.evolver/workspaces/<id>/` without creating automatic `git commit`s.
- **Workbench Draft Preserved (`ok=false`, `outcome="draft_preserved"`)**: Any validation failure (`pytest` / `ruff` / `mypy`) or non-improving fitness verdict (`drop`, `flat`, `regression`) settles honestly as `ok=false`. Your workspace edits are **kept intact in place** (and backed up under `rejected_stashes/<run_id>/`), a 3-line `actionable_fix` points directly to the failing `file:line`, and **zero unverified genes enter the positive vault**. Fix the cited lines and start the next round.
- **First-Run Environment Gaps (`no_baseline`, `pack_absent`, `unmeasured`)**: Soft-continue with clear advisory `warning`s without faking a Parent baseline or opening sealed `val` material.
- **Hard Security Rollbacks**: Diffs containing secrets/credentials, edits targeting `~/.evolver/`, or `val_seal` breaches are immediately rejected and rolled back.

### 3. One-Command Demos

Test the closed-loop flow without manual setup:

```bash
# 1. Deterministic simulation (no LLM API key required)
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 2. End-to-end closed loop test
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py

# 3. Live LLM execution using DeepSeek
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

---

## 🧭 CLI Command Matrix

Commands are organized logically by lifecycle and domain:

| Domain | Command | Description |
|---|---|---|
| **Autopilot** | `evolver init` | Zero-pollution onboarding (`< 3s`): detect IDEs, wire MCP + hooks, exclude local configs via `.git/info/exclude`, and spawn clean background baseline & Anchor bootstrap |
| | `evolver up` / `auto` | Zero-touch autopilot loop (`--once` for one cycle; adaptive sliding sessions + 3-round dormancy) |
| | `evolver status` | Plain-language health & progress panel (ready lamp, promoted fixes, `saved_validation_seconds`, vault operators, workbench drafts; `--json` for machines) |
| **Evolution** | `evolver run` | Run a single self-evolution cycle (default) |
| | `evolver --loop` | Run continuous autonomous evolution daemon |
| | `evolver --review` | Interactive review mode before mutations apply |
| | `evolver solidify` | Validate (`--validation-scope=related\|cascade`) and settle a pending run. Fitness misses and validation failures settle as `draft_preserved` (`ok=false`; patch kept in place with a 3-line `actionable_fix`, backup under `rejected_stashes/`). First-run environment gaps soft-accept. No auto git commit; hard blocks still roll back. Restore the backup stash with `--restore-stash` |
| | `evolver setup` | First-run entry, same as `doctor --fix` |
| | `evolver doctor` | Diagnose git / freeze pack / Parent baseline / user lock (`--fix` installs the pack; measures a baseline only if val sandboxes are already filled) |
| | `evolver round --host` | Single-entry host workflow chaining `boot → status → tick → checklist` |
| | `evolver migrate-state` | Migrate legacy in-repo `memory/` and `.evolver/gep/` into externalized `~/.evolver/workspaces/<id>/` |
| | `evolver apply-proposal` | Apply a single proposal or selectively compose multiple `INV × DOM` proposals |
| | `evolver session` | Manage paired evolution sessions and hypothesis gates |
| **Swarm & Safety** | `evolver mcp` | Start stdio MCP server for host takeover |
| | `evolver hitl` | Human-In-The-Loop approval management (`list`/`approve`/`reject`) |
| | `evolver supervise` | Human-On-The-Loop supervision (`status`/`pause`/`resume`/`veto`) |
| | `evolver setup-hooks` | Install automated IDE telemetry hooks (Cursor, Claude Code, etc.) |
| | `evolver charter-check` | Verify runtime environment and charter compliance |
| **Assets & Memory**| `evolver skills` | Scan, preview, and synchronize `SKILL.md` files into GEP assets |
| | `evolver distill` | Distill LLM responses into Genes/Capsules (`--strict-transferable`) |
| | `evolver gene-lifecycle`| Audit and govern gene states (`active`/`under_review`/`retired`) |
| | `evolver variants` | Inspect archived rejected variants (`*` re-dispatchable, `~` salvageable) |
| | `evolver library` | Manage content-addressed library snapshots (`establish-parent`/`publish`) |
| | `evolver episode` | List or show Episode Records, or zoom into truncated output with `episode inspect` |
| | `evolver self-report` | Run Autopoiesis self-diagnosis and update living memory |
| **Bench & Eval** | `evolver experiment` | Run controlled ablation experiments (`--ablation`, `--placebo`, `--stage-exit`) |
| | `evolver bench` | Run frozen benchmark packs, baseline gates, and paired library solves |
| | `evolver anchor` | Manage and run out-of-repo frozen anchor verification suites |
| | `evolver gate-report` | Generate acceptance gate soak and graduation reports |
| | `evolver meta-report` | Inspect Table-8 telemetry, descendant quality, and `library_provenance` |
| **Ops & Services** | `evolver check` / `watch`| Health diagnostic inspection and background monitoring |
| | `evolver start` / `stop` | Manage cross-platform system daemon processes |
| | `evolver webui` | Launch local visual dashboard (requires `server` extra) |
| | `evolver proxy` | Launch local A2A distributed proxy (requires `server` extra) |

---

## 🔒 Safety Model & Engineering Guardrails

`evolver.py` modifies code autonomously, which demands strict security guardrails:

- **Git blast radius, dual-track (v1.114.0)**: Genes still cap files (`constraints.max_files`) and list forbidden paths (`forbidden_paths`). Solidify does not auto-commit. A missing pack or baseline soft-continues and soft-accepts; a flat or lower score, or an ordinary validation failure, settles as `draft_preserved` — the worktree is left exactly as the host left it (patch kept, backup under `rejected_stashes/<run_id>/`), and experience is written only under `~/.evolver/workspaces/<id>/`. Hard blocks still roll back: secrets in the diff, edits aimed at `~/.evolver/`, and a `val_seal` breach. Neither soft-accept nor a draft rejection writes the Parent baseline or enters the positive vault.
- **Content Addressing & Hash Integrity**: Asset IDs embed SHA-256 digests (`sha256:...`). Corrupted or tampered records are rejected on load, and incoming data is sanitized by `sanitize.py`.
- **Credential Redaction**: A dedicated redaction engine scrubs API tokens, JWTs, private keys, and passwords before any events, prompts, or logs are written to disk or exposed to WebUI streams.
- **OS-Level Instance Locks**: Workspace integrity is enforced by OS-level locks (`instance_lock.py`), ensuring that exactly one evolver daemon writes to a given repository at any time.

---

## 🗺️ Project Layout

```
src/evolver/
├── cli.py                  # CLI entrypoint, argument parsing, and command dispatch
├── config.py               # Central configuration, runtime thresholds, and env mappings
├── swarm.py                # Swarm protocol: takeover prompts & closed-loop dispatch
├── mcp_server.py           # Stdio MCP server (common/swarm tools & resources)
├── evolve/                 # Core evolution orchestrator
│   ├── runner.py           # Cycle controller and daemon loop runner
│   ├── guards.py           # Preflight checks (load, memory, and environment guards)
│   └── pipeline/           # Asynchronous 7-stage evolution pipeline (Collect to Dispatch)
├── gep/                    # Genome Evolution Protocol (GEP) engine
│   ├── schemas/            # Pydantic schemas (Gene, Capsule, Task, Protocol)
│   ├── lenses.py           # Read-only AST/impact/traceback/contract lenses (val_seal redacted)
│   ├── blackbox.py         # In-band cycle-boundary flight recorder (AST delta, lenses, wall ms)
│   ├── import_graph.py     # Incremental stdlib AST reverse-dependency graph (< 3s L0 funnel)
│   ├── index_db.py         # Unified WAL sqlite3 read-index (signals, operator stats, episodes)
│   ├── episode_record.py   # Content-addressed Episode Records, attribution & contrast notes
│   ├── working_memory.py   # Session-scoped WORKING_SESSION.md & workspace-fact isolation
│   ├── record_route.py     # Dual-route record orchestration & INV × DOM orthogonal scopes
│   ├── proposal.py         # Structured gene proposals & mechanical selective composer
│   ├── policy_check.py     # Safety policy, cost hierarchy gate & deliverable conformance
│   ├── variant_archive.py  # DGM-style rejected variant archive & semantic salvage
│   ├── library.py          # Content-addressed library snapshots & paired prompt blocks
│   ├── asset_store.py      # Layered JSON/JSONL asset persistence
│   ├── hitl.py             # Human-In-The-Loop approval gate
│   ├── supervision.py      # Human-On-The-Loop supervision & tripwires
│   ├── skill_assets.py     # Skill ecosystem bridge and distiller
│   ├── gene_lifecycle.py   # Gene lifecycle state machine governance
│   └── solidify.py         # Staging, gates, dual-track settle (draft_preserved vs promote); no auto-commit
├── bench/                  # Frozen task packs, scoring harnesses, and statistical checks
├── experiment/             # Controlled ablation suite (placebo arms, sufficiency audits)
├── adapters/               # IDE hooks and telemetry adapters (Cursor, Claude Code, Codex)
├── proxy/                  # Local A2A distributed proxy and model routing
└── webui/                  # Embedded read-only dashboard & real-time SSE streams
```

---

## 📚 References & Further Reading

- **[Step-by-Step Hands-On Tutorials (tutorials/)](tutorials/README.md)** *(Chinese)*: A 5-part, jargon-free guide that builds `evolver.py` from concrete experiments and first principles.
- **[演进方案.md](演进方案.md)** *(Evolution Charter)*: Current charter (*Zero-Touch Self-Evolution: Operators as Genes, Replay as Adjudication*), advancing beyond the archived "Experience as Evidence" stage ([`演进方案_经验即证据.md`](演进方案_经验即证据.md)) into zero-touch onboarding, executable operator genes, and dual-source time-capsule replay adjudication.
- **[TODO_VISTA.md](TODO_VISTA.md) & [TODO_HARNESS2.md](TODO_HARNESS2.md)**: Mechanical harness checklists covering VISTA scene inspection/compaction gates and Harness2 (`H2-1`..`H2-6`) attribution, workspace-fact isolation, and selective composition.
- **[AGENTS.md](AGENTS.md)**: Guidelines, conventions, and architectural rules for AI coding agents.
- **[DEBUG.md](DEBUG.md)**: Field debugging guide for distributed locking, race conditions, and dogfooding edge cases.
- **[CHANGELOG.md](CHANGELOG.md)**: Chronological ledger of updates and release milestones.
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contributor guide and testing specifications.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

> **Lineage Note**: `evolver.py` is an independent, clean-room Python implementation developed from public protocol specifications and test contracts. Original conceptual inspiration derives from the EvoMap organization. This project is independently maintained and distributed under the Apache-2.0 license.
