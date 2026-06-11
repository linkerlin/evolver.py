# 🧬 evolver.py
[【中文】](README.zh.md)

Python 3.12+ port of [`@evomap/evolver`](https://github.com/EvoMap/evolver), a GEP-powered self-evolution engine for AI agents.

This port aims for **full behavioral equivalence** with the Node.js reference implementation while using modern Python tooling:

- **Python 3.12+** — `asyncio`, type parameter syntax, `tomllib`
- **uv** — fast Python package management
- **Pydantic v2** — schema validation and settings
- **httpx** — async HTTP client (equivalent to Node `undici`)
- **FastAPI + uvicorn** — local Proxy and WebUI

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

## Project Structure

```
src/evolver/
├── adapters/          # IDE integration (Cursor, Claude Code, etc.)
├── atp/               # Agent Transaction Protocol (marketplace)
├── cli.py             # Main CLI entrypoint
├── config.py          # Configuration & environment
├── evolve/            # Core evolution pipeline (6 phases)
│   ├── pipeline/      # collect, signals, select, enrich, hub, dispatch
│   ├── runner.py      # Cycle orchestration
│   └── guards.py      # Safety limits
├── force_update.py    # Self-updating engine
├── gep/               # Genetic Evolution Protocol
│   ├── asset_store.py # Gene / Capsule persistence
│   ├── memory_graph.py# Experience memory
│   ├── selector.py    # Gene selection with epigenetics
│   ├── solidify.py    # Mutation application
│   ├── validator/     # Sandbox executor, reporter, stake bootstrap
│   └── ...            # 50+ modules
├── ops/               # Operations (lifecycle, health, self-repair)
├── proxy/             # A2A Proxy (mailbox, sync, lifecycle, routes)
├── recipe/            # Skill registry client
├── scripts/           # Utility scripts (export, report, validate)
└── webui/             # Dashboard & REST API

tests/                 # 80+ test files, pytest
scripts/               # CLI helper scripts
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `EVOLVER_HOME` | `~/.evolver` | Runtime data directory |
| `EVOLVER_LOOP_INTERVAL_MS` | `60000` | Cycle interval in ms |
| `EVOLVER_MAX_CYCLES` | `1000` | Max cycles per run |
| `EVOLVER_MUTATION_TIMEOUT_MS` | `300000` | Mutation timeout |
| `EVOLVER_ROLLBACK_MODE` | `stash` | Rollback strategy |
| `EVOLVER_IDLE_SCHEDULER` | `true` | Enable OMLS idle scheduling |
| `EVOLVER_FORCE_UPDATE` | — | Enable auto self-update |
| `EVOLVER_VALIDATOR_ENABLED` | `true` | Enable validator daemon |
| `EVOLVER_ATP_DAILY_BUDGET` | `10` | ATP daily budget |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI port |
| `EVOLVER_PROXY_PORT` | `19820` | Proxy port |

## Architecture

### Evolution Pipeline (6 Phases)

1. **Collect** — Read MEMORY.md, session logs, system health
2. **Signals** — Extract actionable signals from corpus
3. **Select** — Choose Gene + Capsule with epigenetic bias
4. **Enrich** — Augment with memory advice, hub hits, plateau detection
5. **Hub** — Coordinate with EvoMap Hub / local Proxy
6. **Dispatch** — Build GEP prompt, write solidify state

### Key Concepts

- **Gene** — A reusable mutation strategy (signals_match → execution_trace)
- **Capsule** — A concrete execution instance with outcome
- **Epigenetics** — Environment-aware gene suppression/activation
- **Solidify** — Apply validated mutations to the codebase
- **ATP** — Agent Transaction Protocol for autonomous service marketplace

## Testing

```bash
# Run all tests
uv run pytest tests/ -q

# Run with coverage
uv run pytest tests/ --cov=evolver --cov-report=term-missing

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
| `scripts/validate_modules.py` | Verify all imports |

## License

Apache License 2.0
