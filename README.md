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
        [ Soft-accept (default) / hard accept ]
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

### Running Evolver

```bash
# Run a single evolution cycle
uv run evolver run

# Run in continuous daemon loop
uv run evolver --loop

# Run in review mode (pauses for human review before solidifying)
uv run evolver --review

# Check system health
uv run evolver check
```

### First run (`setup` / `doctor`)

The loop starts even when the frozen pack or Parent baseline is missing. Those gaps are warnings. Run the open-box commands once so you can see what is still recommended:

```bash
uv run evolver doctor          # git, freeze pack, Parent baseline, user lock
uv run evolver doctor --fix    # installs the freeze pack; measures a baseline only if val sandboxes are already filled
uv run evolver setup           # same as `doctor --fix`
```

Exit code `0` means you may continue (`soft_continue`), including when only the pack or baseline is missing. Exit code `2` means a hard blocker (the directory is not a git repo, or a user lock is held). `loop_ready` stays honest: it is true only when git, the pack, and the Parent baseline are all present. `--fix` never invents val answers and never opens sealed val material in the candidate chat.

Runtime state lives outside the source tree, under `~/.evolver/workspaces/<id>/` (`<id>` is `sha256(realpath(repo))[:16]`). If this checkout still has legacy in-repo files (`memory/`, `.evolver/gep/`), move them:

```bash
uv run evolver migrate-state
```

`swarm_status` reports `state_root`, `workspace_id`, and `state_health.legacy_in_repo` (including `migrate_command`). `migration_checklist()` is the same recommendation as a dict for callers that want `{needed, step}`.

> **Optional Services**: To enable the visual WebUI dashboard or the local A2A proxy, install the `server` extra:
> ```bash
> uv sync --extra server
> uv run evolver webui   # Opens dashboard at http://127.0.0.1:8080
> uv run evolver proxy   # Starts local A2A proxy on port 8081
> ```

---

## 🛠️ Connecting Your Host Agent (MCP Configuration)

Integrate `evolver.py` as an MCP Server into your development environment so host agents can execute mutations.

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
      "args": ["-m", "evolver.mcp_server"],
      "env": {
        "EVOLVER_SWARM_AUTO_HIJACK": "0"
      }
    }
  }
}
```

After `uv sync`, a pull, or any install, **restart the MCP server**. A long-lived `evolver mcp` process keeps the old modules in memory. `swarm_boot` and `swarm_status` expose `source_revision` (the git SHA of the running source tree) next to `code_staleness`; boot also auto-acks this agent's own pending `swarm.hello`.

Live `tools/list` already publishes `swarm_tick` parameters `prompt_mode` (`full` or `short`) and `checklist_only`, with descriptions on those fields, and read-only `swarm_doctor`. A host catalog that still lists only `agent_name` and `include_prompt`, or that cannot find `swarm_doctor`, is a stale client session. Restarting the server reloads the code; start a new host session so the client reads `tools/list` again.

If a previous run is unfinished, `swarm_boot` keeps `next_action=swarm_solidify`, sets top-level `pending_solidify`, and adds `readonly_smoke` (`tools`: `swarm_doctor` and `swarm_status`, `settles_run`: false). On a soft gap it also sets `tick_again=false` while `gate_soft_continue` stays true. `hint` says to solidify first. A soft gap (`no_baseline` / `pack_absent` / `unmeasured`) still attaches `warning` and `next_steps`, and it does not replace that hint or weaken the gate. A read-only smoke can call `swarm_doctor` or `swarm_status`; neither settles the run nor invents a Parent baseline. A `swarm_tick` in that state does not start a cycle. The first call stays soft (`ok` true, `severity` soft, `cycle_started` false, `progress` false, `redirect_count` 1, `retryable` false, `next_action` still `swarm_solidify`, `last_run` unchanged). An omitted `retryable` is not a license to tick again. The same call again on that run returns `ok` false, `loop_fuse=pending_redirect_loop`, `redirect_reason=pending_redirect_loop`, `severity` soft, `retryable` false, and no `error` field. It still does not start a cycle. `loop_fuse` and that `redirect_reason` are the tick-loop fuse. The code is not an `error` and not a `next_action`. `next_action` stays `swarm_solidify`. `dispatch_reason` stays `pending_solidify`. The first redirect keeps `redirect_reason=pending_solidify` and does not set `loop_fuse`. Connect-time instructions name `loop_fuse=pending_redirect_loop` the same way. The fuse is not a gate failure and not an abandon signal; a soft gap stays on `warning` and `next_steps`. Both returns set `preserve_pending` true, `abandon_run` false, and `action_required` to `swarm_solidify` (boot and status do too while solidify is still next). Do not drop the unfinished run. When a soft gap is present, `gate_soft_continue` is omitted on the first redirect and on the fuse (`tick_again` is false). Omitted is not false: the first redirect keeps `ok` true and sets no `error`, so a host that treats only a strict false as session death stays in the session and does not tick again. Both tick returns set `session_not_failed` true. Read that field before other flags: true means the session is not failed, and `loop_fuse` does not abandon the run when the preserve flags say to call `swarm_solidify`. `next_steps` starts with `swarm_solidify`. Boot and status keep `gate_soft_continue` true while a run is still unfinished, set `tick_again` false on that soft gap, and they do not set `session_not_failed`. Pass `supersede_pending=true` to replace that run. Pause and the compaction checkpoint still refuse the cycle.

A cold `swarm_status` (this process has not called `swarm_boot`) returns `next_action=swarm_boot` and a short hint. After boot, status keeps `agent_name`, `source_revision`, and any soft `gap` / warnings. `tool_asset_search`, `tool_mailbox_poll`, `tool_cycle_timeline`, and `swarm_approvals` always return `{ok, items, hint}` — an empty match is not a blank body. `swarm_approvals` also keeps `pending` (the same rows as `items`) and `recent`. Read-only `swarm_doctor` mirrors `evolver doctor` without `--fix` (`ok`, soft warnings, command hints in `fixes`). `no_baseline` / `pack_absent` / `unmeasured` stay soft-continue. When a run is unfinished and that report is soft-continue, doctor also sets `next_action=swarm_solidify`, `tick_again=false`, `pending_solidify`, and the preserve triad (`preserve_pending`, `abandon_run=false`, `action_required=swarm_solidify`). `soft_continue` stays true. It still does not settle the run, write a Parent baseline, or execute `evolver doctor --fix`. `gate_soft_continue` and `session_not_failed` stay absent. A hard blocker keeps `ok` false and does not add that action or `tick_again`. The first unfinished-run tick and the fuse already set `tick_again` false.

`swarm_boot(project=...)` binds a directory only when that path exists. `bound_paths.repo_root` is the code root (the git root walked from that directory, or the directory itself). `bound_paths.workspace_root` is the mutation directory. When they differ, or when `project` is a free-text label rather than a directory, the same object carries `warning` and `next_steps`. That is a soft warning: `ok` stays true and the loop still continues. A label is not turned into a new workspace.

On Grok Bot the evolution workspace root is `/workspace` and the evolver.py checkout is `/workspace/evolver-research/evolver.py`. Point `EVOLVER_REPO_ROOT` at the checkout. The full env block is in [`examples/swarm-quickstart/README.md`](examples/swarm-quickstart/README.md).

### 2. Closed-Loop Protocol Flow

Once connected, host agents communicate via standardized tool calls:
1. `swarm_boot`: Initializes the evolution session and reports status.
2. `swarm_tick`: Retrieves the latest GEP mutation prompt and context (including `[attribution]` and `[contrast]` notes from the prior episode). The default is `prompt_mode=full`, which inlines the gene preview. A short payload requires an explicit `prompt_mode=short` or `checklist_only=true`: the reply is the core-loop checklist, `engine_log` drops the inlined GEP text, and the full prompt stays in `last_prompt.md` (`dispatch_prompt_artifact`, resource `evolver://dispatch/last`).
3. `swarm_propose` *(optional)*: Validates structured gene proposals against the `H2-4` component cost hierarchy (`check_component_integrity`) or mechanically composes multiple `INV × DOM` candidates (`candidates`) before editing.
4. *(Host edits code and applies refactorings)*
5. `swarm_distill`: Extracts structured Gene and Capsule data from the diff (with optional `strict_transferable` triad auditing and automatic `confounded` round filtering).
6. `swarm_hypothesis`: Declares the single testable hypothesis for the round, with an optional `expected_outcome` listing the checks expected to pass.
7. `swarm_solidify`: Runs the gates and settles the round. The default is **soft-accept** (see below). The engine records `prediction_delta` by comparing `expected_outcome` with the checks that actually ran.
8. `swarm_feedback`: Reports multi-dimensional metrics to steer future cycles.

When the previous round's check output or diff is clipped, or when the host is about to compact its context, two companion tools keep the loop grounded:
- **Zoom into truncated evidence (`episode_inspect`)**: The prompt carries a bounded summary (for example, `stdout truncated at 400/2208 chars; call episode_inspect to zoom in`). Instead of guessing, the host passes a concrete question and a line window (such as `{"kind":"check","name":"pytest","offset_lines":0,"limit_lines":80}`) to read the raw scene without modifying `episode.json`.
- **Save session scratch before compaction (`swarm_checkpoint_working`)**: A `precompact` hook or four consecutive failed solidifications pauses mutation tools until the host writes the active hypothesis, ruled-out approaches, and key episode IDs to `WORKING_SESSION.md` (16,000-char cap). `swarm_boot` returns the full text, the next dispatch prompt appends a `[host_working]` clue after the evidence pack, and session boundaries archive and unlink the file so scratch never leaks into durable memory.

For the first five ticks, and only when no run is waiting to solidify, the instrument prompt returned by `swarm_boot` adds **Core Loop Tools / 核心循环工具**: tick → edit → distill → hypothesis → solidify → feedback. Follow each tool's `next_action`.

#### Soft-accept is the default MCP path

`no_baseline`, `pack_absent`, `unmeasured`, `drop`, `flat`, and `regression` no longer stop the loop. Boot and `swarm_tick` **soft-continue** (`severity=soft`, plus `gap` / `warning` / `gate_soft_continue` — these are not a hard `error`). `swarm_solidify` and session Accept **soft-accept**:

- The round is fast. Warnings and `next_steps` are normal on a first run.
- Experience (events, and the episode when the swarm layer records the round) is written only under `~/.evolver/workspaces/<id>/`.
- Solidify does **not** create a git commit. The worktree stays as the host left it. Publishing is a later human step (`evolver session accept`).
- Soft-accept does **not** write the Parent baseline and does not open sealed val material. The measurement layer still records the original reason.

Soft-accept selects a minimal T0 probe (`determine_t0_mode` returns `minimal`; `skip` is also implemented). The acceptance hook (`solidify_hook`) uses that depth when the run is already marked `soft_accept`. A hard accept still runs the full T0 suite. If the settled verdict includes a skip or minimal probe, its warnings contain `t0_skipped_soft` or `t0_probe=minimal`.

`pending_solidify` is true only while `last_run.run_id` differs from `last_solidify.run_id`. A successful solidify, including soft-accept, writes `last_solidify`, so the next status or boot reports `pending_solidify: false` and the opening action returns to `swarm_tick`. While a run is pending, `boot_once` is empty and the host solidifies first.

These still hard-stop (do not retry the same failure): secrets or credentials in the diff, edits that rewrite engine state under `~/.evolver/`, and a `val_seal` breach. A damaged bench gate (`gate_error`) and an anchor failure on a verifier-surface edit also reject. Declaring no hypothesis still refuses the round (`hypothesis_missing`) until `swarm_hypothesis` succeeds.

`EVOLVER_SWARM_GATE_HANDOFF=hotl` is a label in the instrument prompt. It is not a switch that is required before the loop may tick. The default (`human`) already soft-continues.

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
| **Evolution** | `evolver run` | Run a single self-evolution cycle (default) |
| | `evolver --loop` | Run continuous autonomous evolution daemon |
| | `evolver --review` | Interactive review mode before mutations apply |
| | `evolver solidify` | Validate (`--validation-scope=related\|cascade`) and settle a pending run. Default is soft-accept: experience is written, no auto git commit. Hard blocks roll back. Restore a rejected patch with `--restore-stash` |
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

- **Git blast radius, with a soft default**: Genes still cap files (`constraints.max_files`) and list forbidden paths (`forbidden_paths`). Solidify does not auto-commit. On the default path, a missing pack or baseline, a flat or lower score, and ordinary validation failures soft-accept or soft-continue: warnings are expected, the worktree is left as the host left it, and experience is written only under `~/.evolver/workspaces/<id>/`. Hard blocks still roll back: secrets in the diff, edits aimed at `~/.evolver/`, and a `val_seal` breach. Soft-accept never writes the Parent baseline.
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
│   └── solidify.py         # Staging, gates, soft-accept; experience write, no auto-commit
├── bench/                  # Frozen task packs, scoring harnesses, and statistical checks
├── experiment/             # Controlled ablation suite (placebo arms, sufficiency audits)
├── adapters/               # IDE hooks and telemetry adapters (Cursor, Claude Code, Codex)
├── proxy/                  # Local A2A distributed proxy and model routing
└── webui/                  # Embedded read-only dashboard & real-time SSE streams
```

---

## 📚 References & Further Reading

- **[Step-by-Step Hands-On Tutorials (tutorials/)](tutorials/README.md)** *(Chinese)*: A 5-part, jargon-free guide that builds `evolver.py` from concrete experiments and first principles.
- **[演进方案.md](演进方案.md)** *(Evolution Charter)*: Foundational design treatise explaining the shift toward "Experience as Evidence".
- **[TODO_VISTA.md](TODO_VISTA.md) & [TODO_HARNESS2.md](TODO_HARNESS2.md)**: Mechanical harness checklists covering VISTA scene inspection/compaction gates and Harness2 (`H2-1`..`H2-6`) attribution, workspace-fact isolation, and selective composition.
- **[AGENTS.md](AGENTS.md)**: Guidelines, conventions, and architectural rules for AI coding agents.
- **[DEBUG.md](DEBUG.md)**: Field debugging guide for distributed locking, race conditions, and dogfooding edge cases.
- **[CHANGELOG.md](CHANGELOG.md)**: Chronological ledger of updates and release milestones.
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contributor guide and testing specifications.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

> **Lineage Note**: `evolver.py` is an independent, clean-room Python implementation developed from public protocol specifications and test contracts. Original conceptual inspiration derives from the EvoMap organization. This project is independently maintained and distributed under the Apache-2.0 license.
