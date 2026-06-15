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
| `evolver` / `evolver run` | Run a single evolution cycle | ✅ |
| `evolver --loop` / `--mad-dog` | Daemon mode: continuous cycles | ✅ |
| `evolver --review` | Global flag: pause for human review | ✅ |
| `evolver start` / `stop` / `restart` / `status` | Cross-platform daemon lifecycle | ✅ |
| `evolver log` / `check` / `watch` | Tail log, health check, watch supervisor | ✅ |
| `evolver solidify` | Apply pending mutations | ✅ |
| `evolver review` | Review pending solidify state (subcommand) | ✅ |
| `evolver self-report` | Autopoiesis self-check + rule evolution | ✅ |
| `evolver distill` | Distill LLM response → Gene/Capsule | ✅ |
| `evolver fetch <query>` | Fetch skill from Hub | ⚠️ Hub-dependent |
| `evolver sync` | Sync assets with Hub | ⚠️ Hub-dependent |
| `evolver webui [--port=8080]` | Observability dashboard (SSE) | ✅ |
| `evolver proxy [--port=8081]` | Local A2A Proxy (**default port 8081**) | ✅ |
| `evolver setup-hooks` | Runtime hooks: `cursor`, `claude-code`, `codex`, `kiro`, `opencode`; static: `vscode`, `generic` | ✅ |
| `evolver login` / `logout` | OAuth device-code Hub login | ✅ |
| `evolver recipe list|show|apply|…` | Recipe Hub commands | ✅ |
| `evolver replay` / `asset-log` / `exec` | SQLite replay, asset log, bridge exec | ✅ |
| `evolver atp balance\|deposit\|withdraw\|history\|enable\|disable\|status` | Local settlement + auto-buyer consent | ✅ |
| `evolver buy <skill_id>` / `orders` / `verify <order_id>` | ATP Hub client commands | ✅ |
| `evolver atp-complete <task_id>` | Complete ATP task | ✅ |

**IDE adapters:** `setup-hooks --platform=…` delegates to `cursor.py`, `claude_code.py`, `codex.py`, `kiro.py`, `opencode.py` (runtime hooks + scripts). Use `--uninstall` / `--verify` (opencode). Installs always target `--project-dir`.

### Proxy API

CLI serves at `http://127.0.0.1:8081` by default (`EVOLVER_PROXY_PORT` / `EVOMAP_PROXY_PORT`). Routes mount under **`/v1/a2a`** (`proxy/server/__init__.py`). Internal clients use `config.proxy_local_url()`.

Base: `http://127.0.0.1:<port>/v1/a2a`

**Mailbox**
- `POST /mailbox/send` — Send message to Hub
- `POST /mailbox/poll` — Poll inbound messages
- `POST /mailbox/ack` — Acknowledge messages
- `GET /mailbox/list?type=...` — List messages
- `GET /mailbox/status/{msg_id}` — Query message status

**Assets**
- `POST /asset/validate` — Validate asset format ✅
- `POST /asset/fetch` — Fetch from Hub (`asset_id`) or URL; optional `install`
- `POST /asset/search` — Hub semantic search; `local: true` for workspace fallback
- `POST /asset/submit` — Submit asset to Hub
- `GET /asset/submissions` — List local submissions

**Tasks** (local state machine; not full Hub production flow)
- `POST /task/subscribe` / `unsubscribe` / `claim` / `complete`
- `GET /task/list` / `metrics`

**Extensions**
- `GET /extensions/skills/updates` — Pending skill updates
- `POST /extensions/skills/process` — Process skill update queue
- DM / session / trace routes in `proxy/extensions/`

**ATP** (in-memory orders + local settlement; partial)
- `POST /atp/order`, `/atp/deliver`, `/atp/verify`, `/atp/settle`, `/atp/dispute`, …

**Proxy Status**
- `GET /proxy/status` — Proxy health (no auth)
- `GET /proxy/hub-status` — Hub connection status

**LLM Relay**
- `POST /v1/a2a/v1/messages` → Anthropic / Bedrock (SSE streaming)

**Trace** (also at app root)
- `GET /v1/a2a/health`, `GET /v1/a2a/trace`

### WebUI API

CLI entry: `evolver webui` → `webui/app.py` + `dashboard.py` (not `webui/server/http.py`).

| Endpoint | Description |
|---|---|
| `GET /api/status` | System health |
| `GET /api/insights` | Diagnosis, hub gate, autopoiesis, memory sync, preflight abort |
| `GET /api/assets`, `/api/assets/{id}` | Gene / capsule list and detail |
| `GET /api/candidates` | Candidate genes |
| `GET /api/runs` | Evolution run history |
| `GET /api/safety` | Safety events |
| `GET /api/calls`, `/api/lineage`, `/api/interactions` | Call graph, lineage, interactions |
| `GET /api/personality`, `/api/memory-graph`, `/api/skills` | Personality, memory graph, skills |
| `GET /api/pipelines`, `/api/logs` | Pipeline events; logs SSE stream |
| `GET /events/stream` | SSE evolution events (refreshes insights panels on new events) |
| Legacy | `/status`, `/genes`, `/capsules`, `/api/peers`, `/ws` on same app |

### Autopoiesis Governance (md2video port)

Self-maintaining evolution loop wired into the GEP pipeline:

```
collect (living_memory) → signals (guard rules) → hub → enrich
  → autopoiesis (SelfReport + homeostasis) → select → dispatch → solidify
       ↑___________________________________________|  (solidify failure → friction)
```

| Component | Path | Role |
|---|---|---|
| Living memory | `memory/evolution/LESSONS_LEARNED.md` | YAML friction history + human-readable lessons |
| Guard rules | `.evolver/gep/autopoiesis_rules.json` | Auto-encoded checks → `autopoiesis:{rule_id}` signals |
| Self-report | `memory/evolution/self_report.json` | Per-cycle machine-readable report |
| Tick log | `memory/evolution/autopoiesis.jsonl` | Append-only AutopoiesisTick events |

**Integration with GEP evolution:**

- `signals_phase` loads `autopoiesis_rules.json` guard signal keys
- `autopoiesis_phase` merges freshly encoded signals into `ctx["signals"]` (same cycle)
- `autopoiesis_repair_bias` forces `mutation.category=repair` in `select_phase`
- `dispatch` injects `autopoiesis_context` (living memory warnings + viability) into GEP prompt
- `record_solidify_failure` captures solidify errors as friction → living memory
- `hub_degraded` sets one-shot `skip_hub_calls` on the next cycle via `autopoiesis_state.json`

```bash
uv run evolver self-report              # full self-check + rule evolution
uv run evolver self-report --no-write --json   # CI-safe dry run
```

| Variable | Default | Description |
|---|---|---|
| `EVOLVER_AUTOPOIESIS` | `1` | Enable autopoiesis phase |
| `EVOLVER_AUTOPOIESIS_WRITE` | `1` | Persist rules/lessons/reports (`0` = dry run) |
| `EVOLVER_REPAIR_LOOP_DEGRADED` | `1` | Repair-loop trips → degraded repair-only cycle (not hard abort) |
| `EVOLVER_LEARNING_SIGNALS` | `1` | Inject platform/lock learning signals in `signals_phase` |

**P3 integrations (selector + solidify + preflight):**

- `selector` applies `livingMemoryHints` score penalties / repair boosts
- `post_solidify_hooks` records `solidify_success` friction (no auto rule encode)
- `preflight abort` runs read-only SelfReport → `ctx["autopoiesis_preflight_abort"]`

**P4 integrations (memory sync + recovery + WebUI):**

- `memory_bridge.bidirectional_memory_sync` — living_memory ↔ memory_graph hints + friction events
- `solidify` failure/success feeds both living memory and `memory_graph` (`friction` / `outcome` / preference)
- `signals_phase` injects `preflight_abort` signals; `apply_preflight_abort_recovery` forces repair bias
- `GET /api/insights` exposes `memory_sync`; dashboard **Memory Sync** panel refreshes on SSE events
- `autopoiesis_preflight_abort.json` persists abort snapshot until a full cycle completes

**P2 integrations (memory + innovation):**

- `memory_bridge` merges living-memory hints into `memory_advice` and `ctx["signals"]` at enrich
- `learning_signals` feeds `learning_signal:*` strings into signals phase
- `select` records `innovation_attempt_id`; `post_solidify_hooks` records innovation outcomes
- `compute_viability` reads innovation ROI as coupling factor

### Feature flags (unified)

Single resolver: `gep/feature_flags.py` (`is_enabled` / `get_all_flags`). Proxy `router/features.py` delegates route checks to the same source.

Env: `EVOLVER_FF_<NAME>=1|0`. Disk layers (low → high): defaults → `evolver/.config/disk_flags.json` → optional `~/.evomap/feature_flags.json` (`EVOMAP_FEATURE_FLAGS_PATH`) → env.

| Flag | Default | GEP | Proxy route |
|---|---|---|---|
| `ENABLE_RECALL_INJECT` | `true` | recall inject | — |
| `ENABLE_REFLECTION` | `true` | post-solidify personality | — |
| `ENABLE_AUTO_DISTILL` | `true` | enrich distill | — |
| `ENABLE_MEMORY_GRAPH` | `true` | outcome / advice | — |
| `ENABLE_LLM_REVIEW` | `true` | LLM review | `llm_messages` |
| `ENABLE_AUTO_BUYER` | `false` | post_cycle buyer | `atp_order` |
| `ENABLE_VALIDATOR` | `true` | validator daemon | `validator_tasks` |
| `ENABLE_SKILL_AUTO_UPDATE` | `false` | — | `skill_update` loop |
| `ENABLE_TRACE_UPLOAD` | `false` | — | `trace_upload` |
| `ENABLE_EXPLORE` / `ENABLE_CURRICULUM` | `false` | optional cognition | — |

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
| `EVOLVER_PROXY_PORT` / `EVOMAP_PROXY_PORT` | `8081` | Local proxy listen port |
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
