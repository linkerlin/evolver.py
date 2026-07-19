# Evolver Examples

> Hands-on guides for every major evolver feature.

## Getting Started

| Example | What You'll Learn | Time |
|---------|------------------|------|
| [hello-world](hello-world/) | Install, configure `.env`, run one cycle, read output | 5 min |
| [daemon-loop](daemon-loop/) | Run continuously, start/stop/status/log, solidify | 10 min |
| [webui](hello-world/) → | Monitor via WebUI dashboard, SSE events, insight panels | 5 min |

## Core Workflows

| Example | What You'll Learn | Time |
|---------|------------------|------|
| [proxy-basics](proxy-basics/) | Start A2A Proxy, mint tokens, curl API calls, LLM relay | 15 min |
| [ide-hooks](ide-hooks/) | Install session hooks for Cursor/Claude Code/OpenCode/Codex/Kiro | 10 min |
| [solo-mode](solo-mode/) | Fully offline mode, no Hub, local-only evolution | 5 min |
| [self-report](self-report/) | Read autopoiesis reports, lessons learned, friction rules | 10 min |

## Asset Lifecycle

| Example | What You'll Learn | Time |
|---------|------------------|------|
| [hub-publish-flow](hub-publish-flow/) | Distill LLM responses, reuse Hub assets, publish genes/capsules | 15 min |
| [skill2recipe](skill2recipe/) | Compose SKILL.md files into GEP Recipes, apply recipes | 10 min |
| [atp-quickstart](atp-quickstart/) | ATP marketplace: seed merchants, auto-buy, deliver, settle | 15 min |

## Environment Variables Quick Reference

```bash
# Essential
ANTHROPIC_API_KEY=sk-ant-...        # LLM API key
OPENCLAW_WORKSPACE=/path/to/project  # Workspace root override
EVOLVER_NO_PARENT_GIT=1              # Disable parent .git traversal

# Daemon
EVOLVER_LOOP_INTERVAL_MS=30000       # Cycle interval (ms)
EVOLVER_LAUNCHER=uv                  # uv|uvx|python|auto

# Autopoiesis
EVOLVER_AUTOPOIESIS=1                # Enable self-check
EVOLVER_AUTOPOIESIS_WRITE=1          # Persist rules/lessons

# Hub
A2A_HUB_URL=https://evomap.ai        # Hub endpoint
EVOLVER_PROXY_PORT=8081              # Proxy listen port

# ATP
EVOLVER_ATP_AUTOBUY=1                # Auto-buyer
EVOLVER_ATP_DAILY_BUDGET=100         # Daily spend cap

# Learning
EVOLVER_LEARNING_SIGNALS=1           # Inject platform signals
EVOLVER_GENE_INERT_BAN_STREAK=8      # Ban inert genes after N cycles
```

## Common Command Quick Reference

```bash
uv run evolver                    # Run one cycle
uv run evolver --loop             # Run daemon loop
uv run evolver --review           # Review before applying
uv run evolver --solo             # Offline isolated mode
uv run evolver solidify           # Apply pending gene
uv run evolver start              # Start background daemon
uv run evolver status             # Daemon status
uv run evolver stop               # Stop daemon
uv run evolver proxy              # Start A2A proxy
uv run evolver proxy-token        # Mint proxy token
uv run evolver webui              # Start dashboard
uv run evolver setup-hooks        # Install IDE hooks
uv run evolver self-report        # Autopoiesis self-check
uv run evolver distill            # Distill LLM response
uv run evolver fetch <query>      # Search Hub for assets
uv run evolver publish <id>       # Publish to Hub
uv run evolver sync               # Sync with Hub
uv run evolver asset-log          # Show asset call log
uv run evolver recipe list        # List Hub recipes
uv run evolver skill2recipe       # Compose skills into recipe
uv run evolver atp balance        # ATP balance
```

## Running Tests

```bash
uv run pytest tests/ -q           # All tests
uv run pytest -m "not slow"        # Exclude slow tests
uv run ruff check src tests        # Lint
uv run mypy src                    # Type check
```
