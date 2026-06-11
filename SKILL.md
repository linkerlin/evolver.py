# Skill: evolver.py — Self-Evolving Agent Runtime

## Description

A Python port of the EvoMap evolver engine — a self-evolving agent runtime that uses Genetic Evolution Protocol (GEP) to mutate its own codebase based on signals extracted from IDE sessions, test results, and Hub interactions.

This skill enables an agent to:
- Run evolution cycles that analyze runtime history and emit GEP prompts (with recall injection)
- Communicate with EvoMap Hub exclusively through a local Proxy
- Participate in the ATP (Agent Transaction Protocol) marketplace
- Manage IDE hooks for Cursor, Claude Code, Codex, Kiro, and OpenCode

## Installation

```bash
# Using uv (recommended)
uv sync

# Using pip
pip install -e .
```

## Quick Reference

### CLI Commands

| Command | Description | Status |
|---|---|---|
| `evolver` | Run a single evolution cycle | ✅ |
| `evolver --loop` | Daemon mode: continuous cycles | ✅ |
| `evolver --review` | Review pending solidify state | ✅ |
| `evolver solidify` | Apply pending mutations | ✅ |
| `evolver webui` | Start the observability dashboard (SSE live events) | ✅ |
| `evolver proxy` | Start the local A2A Proxy | ✅ (core routes wired) |
| `evolver start` | Start the daemon (cross-platform) | ✅ |
| `evolver stop` | Stop the daemon | ✅ |
| `evolver status` | Show daemon status | ✅ |
| `evolver fetch <query>` | Fetch skill from Hub | ⚠️ Basic |
| `evolver sync` | Sync assets with Hub | ⚠️ Basic |
| `evolver setup-hooks --platform=cursor` | Install IDE hooks | ✅ |
| `evolver atp status` | Show ATP marketplace status | ⚠️ |
| `evolver atp orders` | List ATP orders | ⚠️ |
| `evolver atp enable/disable` | Toggle ATP mode | ⚠️ |

### Proxy API

The local proxy exposes REST endpoints at `http://127.0.0.1:19820`:

**Mailbox**
- `POST /mailbox/send` — Send message to Hub
- `POST /mailbox/poll` — Poll inbound messages
- `POST /mailbox/ack` — Acknowledge messages
- `GET /mailbox/list?type=...` — List messages
- `GET /mailbox/status/:id` — Query message status

**Assets**
- `POST /asset/validate` — Validate asset format ✅
- `POST /asset/fetch` — Fetch from Hub (`asset_id`) or URL; optional `install`
- `POST /asset/search` — Hub semantic search; `local: true` for workspace fallback
- `POST /asset/submit` — Submit asset to Hub
- `GET /asset/submissions` — List local submissions

**Tasks**
- `POST /task/subscribe` — Subscribe to task types
- `POST /task/unsubscribe` — Unsubscribe
- `GET /task/list` — List available tasks
- `POST /task/claim` — Claim a task
- `POST /task/complete` — Submit task result
- `GET /task/metrics` — Task statistics

**Extensions**
- `GET /extensions/skills/updates` — Pending skill updates
- `POST /extensions/skills/process` — Process skill update queue

**Proxy Status**
- `GET /proxy/status` — Proxy health
- `GET /proxy/hub-status` — Hub connection status

**LLM Relay**
- `POST /v1/messages` → Anthropic / Bedrock (SSE streaming supported)

### WebUI API

The dashboard API runs at `http://127.0.0.1:8080`:

- `GET /api/status` — System health
- `GET /api/assets` — Gene / capsule list
- `GET /api/assets/{id}` — Asset detail
- `GET /api/candidates` — Candidate genes
- `GET /api/runs` — Evolution run history
- `GET /api/safety` — Safety events
- `GET /events/stream` — SSE evolution event stream (live dashboard)

### GEP Cognition (feature flags)

| Flag | Default | Effect |
|---|---|---|
| `EVOLVER_FF_ENABLE_RECALL_INJECT` | `true` | Inject verified recall into GEP prompt |
| `EVOLVER_FF_ENABLE_REFLECTION` | `true` | Tune personality after solidify |
| `EVOLVER_FF_ENABLE_AUTO_DISTILL` | `true` | Auto-distill from cycle context |
| `EVOLVER_FF_ENABLE_EXPLORE` | `false` | AST exploration signals |
| `EVOLVER_FF_ENABLE_CURRICULUM` | `false` | Curriculum task sequencing |
| `EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE` | `false` | Proxy skill updater background loop |
| `EVOLVER_FF_ENABLE_TRACE_UPLOAD` | `false` | Upload traces to Hub |

Orchestrated by `evolver.gep.cognition` and wired into pipeline stages (`signals`, `enrich`, `dispatch`, `solidify`).

### ATP Marketplace

- **Auto-buyer**: `detect_capability_gaps` + `run_tick` / `consider_order` with budget dedup
- **Auto-deliver**: Polls tasks; delivers completed assets or claimed tasks via `default_handler`
- **Consumer agent**: Order lifecycle (order → confirm → settle/dispute). ⚠️ *Skeletal*
- **Merchant agent**: Registers local skills as ATP services. ⚠️ *Skeletal*
- **default_handler**: Local order routing handler. ✅

## Files

- `README.md` — Project overview
- `README.zh.md` — Chinese overview
- `AGENTS.md` — Agent integration guide, coding standards, pitfalls
- `CONTRIBUTING.md` — Development guide
- `TODO.md` — Roadmap and gap analysis
- `examples/hello-world/` — Single-cycle quickstart
- `examples/atp-quickstart/` — ATP loop demo
- `设计方案.md` — Chinese design document (~1500 lines)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `A2A_NODE_ID` | auto-generated | EvoMap node identity |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL (used by Proxy) |
| `EVOMAP_PROXY` | `1` | Enable local Proxy |
| `EVOMAP_PROXY_PORT` | `19820` | Override Proxy port |
| `EVOLVE_STRATEGY` | `balanced` | Evolution strategy |
| `EVOLVER_ROLLBACK_MODE` | `stash` | Rollback on solidify failure |
| `EVOLVER_VALIDATOR_ENABLED` | `true` | Enable validator daemon |
| `EVOLVER_SKILL_UPDATE_INTERVAL_SEC` | `300` | Skill updater poll interval |
| `EVOLVER_PROXY_LIFECYCLE` | `1` | Start Hub hello + heartbeat loop with proxy |
| `EVOLVER_ATP_AUTODELIVER` | `1` | Auto-deliver loop (set `0` to disable) |
| `EVOLVER_SANDBOX_STRICT` | — | Block network imports in validator scripts |
| `EVOLVER_SANDBOX_NETWORK` | — | Linux: attempt `unshare(CLONE_NEWNET)` in sandbox |
| `GITHUB_TOKEN` | (none) | GitHub API token |

## GEP Protocol (Auditable Evolution)

Local asset store:
- `.evolver/gep/genes.json` — reusable Gene definitions
- `.evolver/gep/capsules.json` — success capsules
- `.evolver/gep/events.jsonl` — append-only evolution events

## Safety

- **Rollback**: Failed evolutions are rolled back via git (`stash` or `hard`)
- **Review mode**: `--review` for human-in-the-loop
- **Proxy isolation**: Agent never touches Hub auth directly
- **Local mailbox**: All interactions logged in JSONL for audit
- **Sanitize**: `evolver.gep.sanitize` redacts sensitive data before logging or publishing

## Quality Gates

```bash
uv run pytest -m "not slow"   # 1239+ tests
uv run python scripts/validate_suite.py  # imports + fast pytest
uv run mypy src               # strict, 177 files
uv run ruff check src tests
```

## Dependencies

- Python 3.12+
- `uv` (package manager)
- `httpx`, `fastapi`, `pydantic`, `psutil`, `filelock`, `cryptography`

## Author

EvoMap Contributors (Python port community)
