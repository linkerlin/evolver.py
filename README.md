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

2. **Experience as Evidence**  
   Drawing from modern autonomous research protocols (*arXiv:2609.37968v2, SelfSearch*), the engine treats an agent's runtime execution record (**Episode Record**) as a first-class source of evidence. Rather than mutating blindly or relying on uncalibrated LLM self-scoring, every strategy promotion is backed by controlled ablation tests and statistical sample-size sufficiency audits.

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
                [ Passed Validation ]
                         │
                         ▼
             ┌───────────────────────┐
             │ Solidify & Retain     │ ── Git commit ➔ Gene lifecycle promotion
             └───────────────────────┘
```

### 1. Seven-Stage Evolution Pipeline

Every evolution cycle proceeds through seven decoupled asynchronous phases:
- **Collect**: Scans local run logs, inspects failures, and reads the `LESSONS_LEARNED.md` living memory organ.
- **Signals**: Extracts structured signals (e.g., `log_error`, `perf_bottleneck`, environment dependency drift).
- **Hub**: Interacts with local or remote Hub networks to discover relevant prior strategies and tasks.
- **Enrich**: Bi-directionally synchronizes with the memory graph, assembling past interventions and lessons.
- **Autopoiesis**: Maintains system homeostasis by automatically turning recurring engineering friction into protective guard rules.
- **Select**: Evaluates epigenetic affinities, balancing repair bias against novelty exploration.
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

---

## 🚀 Quick Start

### Prerequisites

- **Python >= 3.12**
- **[Git](https://git-scm.com/)** (Required: used for blast radius calculation, staging, and atomic rollbacks)
- **[uv](https://docs.astral.sh/uv/)** (Recommended modern Python packaging tool)

```bash
# Clone the repository and install dependencies
git clone https://github.com/evomap/evolver.py.git
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

### 2. Closed-Loop Protocol Flow

Once connected, host agents communicate via standardized tool calls:
1. `swarm_boot`: Initializes the evolution session and reports status.
2. `swarm_tick`: Retrieves the latest GEP mutation prompt and context.
3. *(Host edits code and applies refactorings)*
4. `swarm_distill`: Extracts structured Gene and Capsule data from the diff.
5. `swarm_hypothesis`: Declares the single testable hypothesis for the round.
6. `swarm_solidify`: Executes validation gates and commits changes via Git.
7. `swarm_feedback`: Reports multi-dimensional metrics to steer future cycles.

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
| | `evolver solidify` | Apply, validate, and commit pending mutations to Git |
| | `evolver session` | Manage paired evolution sessions and hypothesis gates |
| **Swarm & Safety** | `evolver mcp` | Start stdio MCP server for host takeover |
| | `evolver hitl` | Human-In-The-Loop approval management (`list`/`approve`/`reject`) |
| | `evolver supervise` | Human-On-The-Loop supervision (`status`/`pause`/`resume`/`veto`) |
| | `evolver setup-hooks` | Install automated IDE telemetry hooks (Cursor, Claude Code, etc.) |
| **Assets & Memory**| `evolver skills` | Scan, preview, and synchronize `SKILL.md` files into GEP assets |
| | `evolver gene-lifecycle`| Audit and govern gene states (`active`/`under_review`/`retired`) |
| | `evolver episode` | Inspect past self-improvement records (Episode Records) |
| | `evolver self-report` | Run Autopoiesis self-diagnosis and update living memory |
| **Bench & Eval** | `evolver experiment` | Run controlled ablation experiments (`--ablation`, `--placebo`) |
| | `evolver bench` | Run frozen benchmark packs, baseline gates, and paired tests |
| | `evolver gate-report` | Generate acceptance gate soak and graduation reports |
| | `evolver meta-report` | Inspect evolutionary telemetry and descendant mutation quality |
| **Ops & Services** | `evolver check` / `watch`| Health diagnostic inspection and background monitoring |
| | `evolver start` / `stop` | Manage cross-platform system daemon processes |
| | `evolver webui` | Launch local visual dashboard (requires `server` extra) |
| | `evolver proxy` | Launch local A2A distributed proxy (requires `server` extra) |

---

## 🔒 Safety Model & Engineering Guardrails

`evolver.py` modifies code autonomously, which demands strict security guardrails:

- **Git Blast Radius Control**: All modifications are bounded by Git. Clean snapshots are saved before mutation via `git stash`. Genes specify strict file limits (`constraints.max_files`) and forbidden paths (`forbidden_paths`). Any gate failure triggers an immediate, atomic rollback.
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
│   ├── asset_store.py      # Layered JSON/JSONL asset persistence
│   ├── hitl.py             # Human-In-The-Loop approval gate
│   ├── supervision.py      # Human-On-The-Loop supervision & tripwires
│   ├── skill_assets.py     # Skill ecosystem bridge and distiller
│   ├── gene_lifecycle.py   # Gene lifecycle state machine governance
│   └── solidify.py         # Mutation staging, test gating, and Git solidification
├── bench/                  # Frozen task packs, scoring harnesses, and statistical checks
├── experiment/             # Controlled ablation suite (placebo arms, sufficiency audits)
├── adapters/               # IDE hooks and telemetry adapters (Cursor, Claude Code, Codex)
├── proxy/                  # Local A2A distributed proxy and model routing
└── webui/                  # Embedded read-only dashboard & real-time SSE streams
```

---

## 📚 References & Further Reading

- **[演进方案.md](演进方案.md)** *(Evolution Charter)*: Foundational design treatise explaining the shift toward "Experience as Evidence".
- **[AGENTS.md](AGENTS.md)**: Guidelines, conventions, and architectural rules for AI coding agents.
- **[DEBUG.md](DEBUG.md)**: Field debugging guide for distributed locking, race conditions, and dogfooding edge cases.
- **[CHANGELOG.md](CHANGELOG.md)**: Chronological ledger of updates and release milestones.
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contributor guide and testing specifications.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

> **Lineage Note**: `evolver.py` is an independent, clean-room Python implementation developed from public protocol specifications and test contracts. Original conceptual inspiration derives from the EvoMap organization. This project is independently maintained and distributed under the Apache-2.0 license.
