# Daemon Loop Quickstart

> Run evolver as a **persistent daemon** — continuous evolution cycles with lifecycle management.

## Prerequisites

- Python 3.12+ and `uv` installed
- A git repository (or use `EVOLVER_NO_PARENT_GIT=1` for isolated mode)
- `.env` file with your LLM API key (see [hello-world](../hello-world/README.md))

## 1. Run the daemon loop (foreground)

```bash
cd /path/to/your/project
uv run evolver --loop
```

This runs continuous evolution cycles in the foreground. Each cycle:
- Collects session signals from `memory/`
- Queries the Hub for matching genes/capsules
- Enriches context with cognitive recall
- Runs autopoiesis self-check
- Selects the best gene/capsule for the current situation
- Dispatches a GEP prompt for LLM execution

Press `Ctrl+C` for graceful shutdown (one cycle completes before exit).

### Control the daemon cycle interval

```bash
# Run with 60-second interval between cycles (default: 30s)
EVOLVER_LOOP_INTERVAL_MS=60000 uv run evolver --loop

# Run with review mode — pause after each prompt for human approval
uv run evolver --loop --review

# Run a single cycle then exit
uv run evolver run
```

## 2. Run as a background daemon

```bash
# Start the daemon in the background
uv run evolver start

# Check daemon status
uv run evolver status

# Tail the daemon log
uv run evolver log --lines 50

# Run a health check
uv run evolver check

# Watch health continuously (supervisor mode)
uv run evolver watch

# Stop the daemon
uv run evolver stop

# Restart
uv run evolver restart
```

### How it works

The `start` command spawns evolver as a detached background process:
- PID file: `memory/evolver_loop.pid`
- Log file: `logs/evolution.log` (configurable via `EVOLVER_LOGS_DIR`)
- The daemon uses the same `.env` file and environment variables as the foreground mode
- `uv run` is automatically used if the project has a `pyproject.toml`

### Configure the loop command

The daemon uses `EVOLVER_LOOP_COMMAND` to determine how to spawn itself:

```bash
# Default (auto-detected via uv runtime)
EVOLVER_LAUNCHER=uv uv run evolver start

# Explicit python path
EVOLVER_LAUNCHER=python uv run evolver start

# Custom command
EVOLVER_LOOP_COMMAND="python -m evolver --loop" uv run evolver start
```

## 3. Operate the daemon

### Apply pending mutations (solidify)

```bash
# After a cycle produces a gene, apply it
uv run evolver solidify

# Review before applying
uv run evolver review
```

### Check the asset call log

```bash
# Show recent Hub asset interactions
uv run evolver asset-log

# Filter by action
uv run evolver asset-log --action asset_reuse --last 20

# JSON output
uv run evolver asset-log --json
```

### Sync with Hub

```bash
# Fetch tasks and download assets from Hub
uv run evolver sync

# Dry-run mode
uv run evolver sync --dry-run

# Force re-sync
uv run evolver sync --force
```

## 4. Configure for production

```bash
# Example .env for production daemon
EVOLVER_LOOP_INTERVAL_MS=120000       # 2 min between cycles
EVOLVER_REPAIR_LOOP_DEGRADED=1        # Degraded mode on repair loops
EVOLVER_AUTOPOIESIS=1                  # Enable self-check
EVOLVER_AUTOPOIESIS_WRITE=1            # Persist autopoiesis rules
EVOLVER_LEARNING_SIGNALS=1             # Inject learning signals
EVOLVER_GENE_INERT_BAN_STREAK=8        # Ban inert genes after 8 cycles
EVOLVER_ROLLBACK_MODE=stash            # Stash before rollback
A2A_HUB_URL=https://evomap.ai         # Hub endpoint
```

## 5. WebUI monitoring

```bash
# Start the WebUI dashboard in one terminal
uv run evolver webui --port 8080

# Access at http://localhost:8080
# Shows: system status, gene/capsule tables, pipeline insights,
#        asset economics, system health, daemon lifecycle,
#        persona commentary, skills monitor
```

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| `evolver start` says "already running" | `uv run evolver stop && uv run evolver start` |
| Daemon starts but no cycles happen | Check `logs/evolution.log`; verify Hub is reachable |
| `EVOLVER_REPO_ROOT` not set correctly | Set explicitly or run from the repo root |
| "system load exceeds threshold" | The daemon skips cycles when CPU is busy; normal behavior |
| Power/sleep causes clock jump | The `watch` supervisor detects this and restarts automatically |
