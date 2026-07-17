# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**a GEP-powered self-evolution engine for AI agents.**

This project aims for **full behavioral equivalence**  while using modern Python tooling:

- **Python 3.12+** — `asyncio`, type parameter syntax (`list[str]`), `tomllib`
- **uv** — fast Python package management
- **Pydantic v2** — schema validation and settings
- **httpx** — async HTTP client (equivalent to Node `undici`)
- **FastAPI + uvicorn** — local Proxy and WebUI

> **Note**: Core GEP data layer, evolution pipeline, Proxy routes, and advanced cognition orchestration are largely implemented. ATP commercial loops, some Hub asset routes, and production-grade validator sandboxing remain partial. See [Implementation Status](#implementation-status) below.

---

## Quick Start

```bash
# Install dependencies
uv sync

# Run a single evolution cycle
uv run evolver

# Daemon loop
uv run evolver --loop

# Review mode
uv run evolver --review

# Start the WebUI dashboard
uv run evolver webui

# Start the local A2A Proxy
uv run evolver proxy
```

## Prerequisites

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — Required. Evolver uses git for rollback, blast radius calculation, and solidify. Running in a non-git directory will fail with a clear error message.
- **[uv](https://docs.astral.sh/uv/)** — Recommended package manager. Standard `pip` also works.

## Project Structure

```
src/evolver/
├── cli.py              # CLI entrypoint (886 lines)
├── config.py           # Environment variables + thresholds
├── canary.py           # Fork-canary: verify CLI loads without crash
├── evolve/
│   ├── runner.py       # Cycle orchestration (single + daemon loop)
│   ├── guards.py       # Preflight checks (load, RSS, cooldown)
│   ├── post_cycle.py   # Post-cycle hooks (ATP auto-buyer)
│   └── pipeline/       # Seven pipeline phases + preflight (async functions)
│       ├── collect.py      # Scan logs + load living_memory
│       ├── signals.py      # Signals + guard/preflight/learning keys
│       ├── hub.py          # Query Hub; consume autopoiesis skip flag
│       ├── enrich.py       # Memory advice + bidirectional_memory_sync
│       ├── autopoiesis.py  # SelfReport + homeostasis + viability
│       ├── select.py       # Select Gene/Capsule + innovation record
│       └── dispatch.py     # GEP prompt + solidify state persistence
├── gep/                # GEP (Genome Evolution Protocol) core
│   ├── schemas/        # Pydantic models: Gene, Capsule, Task, Protocol
│   ├── asset_store.py  # JSON/JSONL persistence with overlay semantics
│   ├── cognition.py    # Recall/explore/curriculum/reflection pipeline wiring
│   ├── solidify.py     # Apply gene → validate → persist → publish
│   ├── selector.py     # Signal matching + epigenetic bias
│   ├── signals.py      # Signal collection and classification
│   ├── validator/      # Sandbox executor, reporter, stake bootstrap
│   └── ...             # 55+ modules
├── proxy/              # Local HTTP proxy (CLI default 127.0.0.1:8081; routes under /v1/a2a)
│   ├── server/routes.py    # FastAPI route matrix (task/ATP/extensions)
│   ├── router/             # LLM routing, features, SSE streaming
│   ├── extensions/         # DM, session, skill updater, trace control
│   ├── mailbox/store.py    # Local mailbox JSONL storage
│   ├── sync/               # Bidirectional Hub sync engine
│   └── lifecycle/manager.py# Proxy lifecycle + heartbeat
├── atp/                # Agent Transaction Protocol marketplace
│   ├── protocol.py         # Enums and Pydantic models
│   ├── auto_buyer.py       # Auto-discover capability gaps
│   ├── auto_deliver.py     # Auto-claim and deliver tasks
│   └── settlement.py       # Local ledger
├── adapters/           # IDE integration hooks
│   ├── hook_adapter.py     # Shared adapter logic
│   ├── setup_hooks.py      # Install hooks for Cursor, Claude Code, etc.
│   └── scripts/            # Runtime scripts (session_start, signal_detect)
├── ops/                # Operations (lifecycle, health, self-repair)
│   ├── lifecycle.py        # Cross-platform daemon management
│   ├── health_check.py     # Disk/memory/process checks
│   └── self_repair.py      # Git emergency repair
└── webui/              # FastAPI read-only dashboard
    ├── app.py            # Dashboard + SSE `/events/stream`
    ├── dashboard.py      # Self-contained dark HTML dashboard (live events)
    ├── client/           # Inline JS/CSS (SSE, bootstrap, i18n)
    └── observer/         # Data aggregation modules

tests/                  # 130+ test files, 1250+ tests (pytest)
scripts/                # 17 CLI helper scripts (see Scripts section)
assets/gep/             # Seed gene library
memory/                 # Runtime data (graph JSONL, reviews JSONL)
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | Runtime data directory |
| `EVOLVER_REPO_ROOT` | auto-detect | Override repository root |
| `EVOLVE_STRATEGY` | `balanced` | Evolution strategy preset |
| `EVOLVE_BRIDGE` | auto | Git worktree mutation bridge |
| `EVOLVER_ROLLBACK_MODE` | `stash` | Rollback strategy: stash / hard / none |
| `EVOLVER_LOOP_INTERVAL_MS` | `60000` | Cycle interval in ms |
| `EVOLVER_MAX_CYCLES` | `1000` | Max cycles per run |
| `EVOLVER_MUTATION_TIMEOUT_MS` | `300000` | Mutation timeout |
| `EVOLVER_VALIDATOR_ENABLED` | `true` | Enable validator daemon |
| `EVOLVER_ATP_DAILY_BUDGET` | `10` | ATP daily budget |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI port |
| `EVOLVER_PROXY_PORT` | `8081` | Local proxy port (`EVOMAP_PROXY_PORT` alias); override with `evolver proxy --port` |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | auto-generated | Node identity |
| `GITHUB_TOKEN` | — | GitHub API token |
| `EVOLVER_FF_ENABLE_RECALL_INJECT` | `true` | Inject verified recall hints into GEP prompt |
| `EVOLVER_FF_ENABLE_REFLECTION` | `true` | Tune personality after solidify |
| `EVOLVER_FF_ENABLE_EXPLORE` | `false` | AST-based codebase exploration signals |
| `EVOLVER_FF_ENABLE_CURRICULUM` | `false` | Progressive curriculum task sequencing |
| `EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE` | `false` | Proxy skill updater background loop |

## Implementation Status

> **Overall** (2026-06-11): **1239 tests passing**, **mypy strict clean** (181 files). Core loop is usable end-to-end; ATP and Hub asset fetch routes remain the main gaps.

| Subsystem | Status | Notes |
|---|---|---|
| **GEP Data Layer** | ~90% | `asset_store`, schemas, `solidify`, `sanitize`, `crypto` production-grade |
| **GEP Cognition** | ~75% | `cognition.py` wires recall/reflection/distill; explore/curriculum behind flags |
| **Evolution Pipeline** | ~90% | 7 phases + preflight + post_cycle; Autopoiesis + memory_bridge wired |
| **Proxy Infrastructure** | ~85% | Routes under `/v1/a2a`; SSE LLM relay; trace store; port default 8081 |
| **ATP Marketplace** | ~60% | Local settlement + proxy ATP routes; CLI `buy`/`orders`/`atp` argparse wired |
| **IDE Adapters** | ~65% | 4 IDE adapter modules + 4 runtime scripts; `setup-hooks` covers 4 platforms |
| **Ops** | ~75% | `lifecycle`, `health_check`, `skills_monitor`, `innovation`, `trigger` |
| **WebUI** | ~65% | Observer API, SSE client, live dashboard; not a full SPA |
| **Validator** | ~50% | Sandbox framework exists; production network isolation pending |
| **Scripts** | 100% | 17/17 tool scripts in `scripts/` |
| **Tests** | ~79% | 129 test files vs Node.js reference ~164 |

For a detailed gap analysis, see [`设计方案.md`](设计方案.md) (Chinese) and [`TODO.md`](TODO.md).

## Examples

| Example | Description |
|---|---|
| [`examples/hello-world/`](examples/hello-world/) | Run a single evolution cycle in an isolated workspace |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP buyer/deliver/heartbeat demo with mocked Hub |

## Testing

```bash
# Run all tests
uv run pytest tests/ -q

# Run with coverage
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# Run excluding slow tests (CI default)
uv run pytest -m "not slow"

# Lint + type check
uv run ruff check src tests
uv run mypy src

# Validate all module imports
python scripts/validate_modules.py
```

## Scripts

| Script | Purpose |
|---|---|
| `scripts/a2a_export.py` | Export assets to A2A JSON |
| `scripts/a2a_ingest.py` | Import A2A assets |
| `scripts/extract_log.py` | Filter events.jsonl by time/type |
| `scripts/human_report.py` | Generate Markdown evolution report |
| `scripts/generate_history.py` | GEP events timeline (Markdown) |
| `scripts/gep_append_event.py` | Manually append GEP events |
| `scripts/recover_loop.py` | Daemon loop recovery diagnostics |
| `scripts/gep_personality_report.py` | Personality HTML report |
| `scripts/recall_verify_report.py` | Recall/memory-graph coverage |
| `scripts/a2a_promote.py` | Promote candidate gene to active store |
| `scripts/analyze_by_skill.py` | Per-skill evolution event analysis |
| `scripts/build_binaries.py` | PyInstaller standalone build helper |
| `scripts/check_changelog.py` | CHANGELOG vs pyproject version check |
| `scripts/seed_merchants.py` | Seed ATP merchant service definitions |
| `scripts/suggest_version.py` | Semantic version bump suggestion |
| `scripts/validate_modules.py` | Verify all imports |
| `scripts/validate_suite.py` | Imports + fast pytest integration gate |

## Architecture

### Evolution Pipeline

**Preflight** (`guards.py`) → optional abort with persisted SelfReport snapshot.

| Phase | Module | Role |
|---|---|---|
| 1. Collect | `collect.py` | Session logs, failure diagnosis, `living_memory` |
| 2. Signals | `signals.py` | Extract signals; guard / preflight / learning keys |
| 3. Hub | `hub.py` | Hub tasks/assets; hub quality gate data |
| 4. Enrich | `enrich.py` | Memory graph advice, `bidirectional_memory_sync` |
| 5. Autopoiesis | `autopoiesis.py` | SelfReport, viability, homeostasis, repair bias |
| 6. Select | `select.py` | Gene/Capsule + mutation category |
| 7. Dispatch | `dispatch.py` | GEP prompt (`recall` + `autopoiesis_context`), solidify state |

**Post-cycle** (`post_cycle.py`) — ATP auto-buyer tick. **Solidify** (`evolver solidify`) runs separately via `gep/solidify.py`.

### Key Concepts

- **Gene** — A reusable mutation strategy (signals_match → execution_trace)
- **Capsule** — A concrete execution instance with outcome
- **Epigenetics** — Environment-aware gene suppression/activation
- **Solidify** — Apply validated mutations to the codebase
- **ATP** — Agent Transaction Protocol for autonomous service marketplace

## Differences from Node.js Reference

- **License**: Python port uses Apache-2.0; Node.js reference uses GPL-3.0-or-later
- **Source visibility**: Python port is fully readable; Node.js core files are obfuscated
- **Database**: Python port adds `ops/sqlite_store.py` for SQLite persistence (enhancement)
- **Recipe Hub**: Python port includes `recipe/` module (new feature)
- **WebUI frontend**: Python port ships an inline JS client (`webui/client/`) with SSE; not a separate SPA build

## Documentation

- [`设计方案.md`](设计方案.md) — Comprehensive design document (Chinese, ~1500 lines)
- [`TODO.md`](TODO.md) — Detailed gap analysis and roadmap
- [`AGENTS.md`](AGENTS.md) — Agent integration guide, coding standards, pitfalls
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines
- [`SKILL.md`](SKILL.md) — Skill usage reference

## License

[Apache License 2.0](LICENSE)

> This is a community port of the EvoMap evolver engine. The original Node.js reference implementation is distributed by EvoMap under GPL-3.0-or-later.
