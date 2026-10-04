# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**English** · [Chinese](README.zh.md) · [Japanese](README.ja-JP.md) · [Korean](README.ko-KR.md)

**A GEP-powered self-evolution engine for AI agents.**

The engine does not call an LLM. A host agent connected over MCP stdio is the executor. The current stage points that loop at an external frozen task pack; see the [Evolution Charter](演进方案.md) (Chinese). This tree is a behavioral Python port of `@evomap/evolver`, built on:

- **Python 3.12+** — `asyncio`, type parameter syntax (`list[str]`), `tomllib`
- **uv** — fast Python package management
- **Pydantic v2** — schema validation and settings
- **httpx** — async HTTP client (equivalent to Node `undici`)
- **FastAPI + uvicorn** — local Proxy and WebUI (optional `server` extra)

> **Note**: Core GEP, the evolution pipeline, Proxy routes, and cognition are largely implemented. ATP commerce and the validator sandbox remain partial, and they are outside the current stage.

---

## Quick Start

```bash
# Install dependencies (project-local env)
uv sync

# Run a single evolution cycle
uv run evolver

# Daemon loop
uv run evolver --loop

# Review mode
uv run evolver --review

# Start the WebUI dashboard (needs the server extra)
uv run evolver webui

# Start the local A2A Proxy
uv run evolver proxy
```

> WebUI and the local Proxy need the server extra: `uv sync --extra server`. The core evolution engine and the MCP server have no fastapi dependency.

**Let a host agent join the swarm (the flagship capability since v1.98)** — the engine takes the host over MCP stdio and turns it into the executor of GEP mutation prompts. One command runs the full loop:

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py            # deterministic, no LLM
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py     # full closed loop
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm   # DeepSeek executes for real
```

See [MCP Swarm Evolution](#mcp-swarm-evolution) and [examples/swarm-quickstart/](examples/swarm-quickstart/).

### uvx (one-shot / no project install)

When evolver is published (or you want tool isolation without `uv sync`):

```bash
# From PyPI (once published)
uvx evolver --help
uvx evolver run

# From a local checkout (no global install)
uvx --from . evolver run
uvx --from . evolver --loop
```

### Launcher selection

Daemon respawn, lifecycle `start`, and IDE hooks resolve how to re-invoke evolver via
`EVOLVER_LAUNCHER`:

| Value | Behaviour |
|---|---|
| `auto` (default) | Prefer `uv run evolver` when `uv` + project root exist; else `uvx`; else `python -m evolver` |
| `uv` | Force `uv run [--project <root>] evolver …` |
| `uvx` | Force `uvx [--from <root>] evolver …` (or `uv tool run` if no `uvx` shim) |
| `python` | Force `python -m evolver …` |

Supervisors can override the full argv with `EVOLVER_LOOP_COMMAND` (space-separated).

## MCP Swarm Evolution

Through its stdio MCP server, evolver turns **the host agent into the executor of GEP mutation prompts**. The engine never schedules LLM API calls itself; the connected host (ZCode / Claude Code / Cursor / …) *is* the executor (v1.98.0+).

### Host configuration

The launch command is one of `uv run evolver mcp` (inside the project) or `<venv>/bin/python -m evolver.mcp_server` (absolute path — recommended for host configs).

**ZCode** (workspace/user `settings` `mcpServers`):

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

**Claude Code** (project-root `.mcp.json`) and **Cursor** (`.cursor/mcp.json`) are shaped the same way:

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

Ready-made host configs live in [`examples/swarm-quickstart/mcp-host-configs/`](examples/swarm-quickstart/mcp-host-configs/).

> Frequently used environment variables: `EVOLVER_SWARM_AUTO_HIJACK=1` (force HITL on and refuse host-relayed approvals; the standing instructions do not change); `EVOLVER_HITL_MODE=on` (high-risk solidify needs human approval); `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` (auto-pause after N consecutive degraded feedbacks, default 3).

### Takeover and closed loop

- **Injection**: if this message already carries another task, do that task; otherwise call `swarm_boot` and state the actual status in one sentence. `boot_once` only registers the session — it does not sync skills at boot. When the frozen pack or the Parent baseline is missing, or the loop is paused, no tick runs (a human can set `EVOLVER_SWARM_GATE_HANDOFF=hotl` to skip the first two; the gate still refuses to publish). Say "stop" / "continue" and the host relays `swarm_supervise` pause / resume. First-time setup (frozen pack, unsealing val in another context, baseline) is described in [examples/swarm-quickstart/README.md](examples/swarm-quickstart/README.md). The full protocol ships in the `evolver_swarm` prompt and in `swarm_boot`'s response
- **Closed-loop protocol**: `swarm_tick` (take the GEP mutation prompt) → the host executes the mutation with its own editing tools → `swarm_distill` (distil Gene/Capsule) → `swarm_hypothesis` (the one-hypothesis gate: the host declares the round's single hypothesis; without one the gate refuses) → `swarm_solidify` (validation gate + solidify) → `swarm_feedback` (unified evaluation signal E; low scores auto-inject repair bias) → loop. `swarm_propose` lets the host raise an intervention proposal from the evidence pack; `swarm_report` is the heartbeat
- **Twin safety gates**: HITL approval gate (`evolver hitl list|approve|reject`, TTL expiry fails safe to REJECT) + HOTL supervision (`evolver supervise status|pause|resume|direct|veto|unveto` — a human can brake, veto, or steer at any time)

### Hooks integration (automatic signal collection)

When the host supports file hooks, install them and session boundaries plus error signals in tool output flow into evolution memory automatically:

```bash
uv run evolver setup-hooks --platform auto --project-dir /path/to/workspace
# platforms: cursor | claude-code | codex | kiro | opencode | vscode | generic | auto
```

MCP-only hosts (no file-hook capability) use the **in-process bridge** instead: call the `swarm_hook_event` tool at session start/end and whenever error output is observed (`event=session_start|session_end|signal_detect`, `payload.content` carries the text). Detected signals (`log_error` / `perf_bottleneck` / …) are injected straight into the next cycle's gene selection. Hosts can also self-install file hooks via `swarm_hooks` (`action=status|install|uninstall`).

### MCP resources and tool annotations

Besides tools, the server exposes four read-only resources (hosts may subscribe or read them without a tool round-trip):

| URI | Content |
|---|---|
| `evolver://status` | Live engine/swarm status (JSON, incl. HITL/HOTL/feedback summary) |
| `evolver://instrument-prompt` | The currently rendered takeover prompt |
| `evolver://dispatch/last` | The most recent GEP mutation prompt (`last_prompt.md`) |
| `evolver://events/recent` | Recent evolution cycle timeline (JSON) |

The tool surface is 26 tools: 8 general tools (`asset_search`, `asset_get`, `episode_get`, `mailbox_send`, `mailbox_poll`, `mailbox_ack`, `rebuild_views`, `cycle_timeline`) and 18 swarm tools (`swarm_boot` / `tick` / `distill` / `hypothesis` / `propose` / `solidify` / `feedback` / `report` / `status` / `approvals` / `approval_resolve` / `supervise` / `hooks` / `hook_event` / `skills` / `workflow_run` / `workflow_act` / `workflow_status`).

Tools carry MCP spec annotations: `swarm_status`, `swarm_approvals`, `asset_search`, `episode_get`, `cycle_timeline` and friends are marked `readOnlyHint` (host plan mode can skip confirmation); `swarm_solidify`, `swarm_hypothesis`, `swarm_propose`, `swarm_supervise`, `swarm_approval_resolve`, and `swarm_workflow_act` are marked `destructiveHint` (hosts may ask the user to confirm).

### Skill ecosystem bridge (SKILL.md → skill genes)

Bridge the host ecosystem's skill files into the evolution engine (EvoX SkillRegistry pattern: **project > user > builtin priority, same-name shadowing**). Discovery roots: workspace `.agents/skills` and `.claude/skills` > user `~/.agents/skills`, `~/.zcode/skills`, `~/.claude/skills` > engine builtin (override with `EVOLVER_SKILL_ROOTS`, order = priority).

```bash
uv run evolver skills scan              # preview discoveries (priority + shadowing)
uv run evolver skills sync --dry-run    # preview skill genes to be installed
uv run evolver skills sync              # convert into the GEP asset store (gene_distilled_s2g-*)
uv run evolver skills list              # list skill genes in the store
```

Once synced, skills participate in signal matching and selection as genes — a "fix ImportError" skill gets selected into the GEP prompt when the signal hits. Hosts can self-serve through the MCP `swarm_skills` tool (`scan|list|sync`).

### Evolution workflows (EvoX harvest: collaboration as data)

A whole stretch of collaboration is expressed as a **YAML workflow** (diffable → evolvable): `agent` steps declare `role`/`instruction` for a host executor to claim, `gate` steps run the validation cascade engine-side (ruff→mypy→pytest), `approval` steps land on the human approval gate — all WAL-durable and resumable (Sprint 24.10 engine + v1.110.0 extensions).

```bash
uv run evolver workflow templates                  # bundled templates: repair / innovate
uv run evolver workflow run --template repair      # start a repair loop (or give a YAML file)
uv run evolver workflow awaiting <id>              # what the host executor/approver owes right now
uv run evolver workflow complete <id> --result '{"ok": true, "files": 2}'
uv run evolver workflow approve <id>               # approve and release
```

MCP side: `swarm_workflow_run` (start from file or template), `swarm_workflow_act` (approve/reject/complete/resume/cancel), `swarm_workflow_status` (full state + host to-dos).

### Controlled experiments & ablation adjudication

Ablation benchmarking validates whether prior episode records genuinely improve host self-repair outcomes (SelfSearch protocol, arXiv:2609.37968v2). Rather than relying on self-asserted score improvements, evolver provides a rigorous, offline/online controlled evaluation harness:

```bash
# Real-LLM ablation over tasks with/without previous episode records
uv run evolver experiment --ablation --tasks tasks.json \
    --from-episodes --placebo --model deepseek-flash --output result.json
```

Key scientific safeguards:
- **Placebo control (`--placebo`)**: replaces an empty context with an equal-length neutral block in the without-records arm, isolating prompt-presence bias so only the *content* of past episodes is evaluated.
- **Stage-exit contract (`--stage-exit`)**: machine-enforces the exit — real episodes + placebo + unique tasks + known commit + on-disk report, or exit 2 with no report. Seeded AB/BA interleaving replaces fixed arm order; per-call records (latency, token splits, error class, served model), a paired exact test over per-task outcomes, frozen sampling params, and a server-side prompt-imbalance meter ship in the report.
- **Sample adequacy audit**: evaluates sample size against `MIN_N=30`; signals from under-powered samples are automatically tagged `indicative only`.
- **Attribution transparency**: distinguishes genuine success-rate gain (`success_rate`) from token tie-breaks (`tokens_only`).
- **Call-graph boundary guard**: the episode recorder is scanned across all `src/` files by a unit test (`test_the_record_writer_is_confined_to_a_declared_boundary`) ensuring mutation and benchmark runners can never record or grade themselves.

## Prerequisites

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — Required. Evolver uses git for rollback, blast radius calculation, and solidify. Running in a non-git directory fails with a clear error message.
- **[uv](https://docs.astral.sh/uv/)** — Recommended. Enables `uv sync`, `uv run`, and `uvx`. Standard `pip` / `python -m` also work.

## CLI Command Reference

| Command | Description |
|---|---|
| `run` | Run one evolution cycle (default) |
| `--loop` / `--solo` / `--review` | Daemon loop / fully offline mode (implies `--loop`) / pause for human review |
| `start` `stop` `restart` `status` `log` | Daemon lifecycle |
| `check` `watch` | Health checks and the health-watch supervisor |
| `solidify` | Apply the pending mutation (or proposal) |
| `apply-proposal` | Mechanically apply a gene proposal JSON (anchors validated, workspace-safe) |
| `review` | Review pending solidify |
| `report` | Per-cycle verdict report (negative results as-is) + patterns projection |
| `gate-report` | Acceptance-gate soak report: shadow metrics + promotion verdict |
| `variants` | Variant archive of rejected-but-retained candidates (RSI P1-3) |
| `charter-check` | Machine receipt: verify charter compliance + drift |
| `anchor init\|list\|run` | Out-of-tree anchor suite: frozen verifier contracts (RSI P0-1) |
| `meta-report` | Improvement-mechanism telemetry: RSI Table-8 panel + descendant quality |
| `gene-lifecycle list\|evaluate\|reinstate` | Gene lifecycle governance (active / under_review / retired) |
| `soak setup\|exports\|status` | Keep evolution runtime state off the git tree |
| `session start\|resume\|status\|round\|hypothesize\|reject\|accept\|incomplete\|extend\|finalize` | Paired evolution session (round budget frozen at 8; `extend` is human-only) |
| `self-report` | Autopoiesis self-report and rule evolution |
| `bench list\|init\|freeze\|gate\|baseline\|run\|prompt\|grade\|compare` | Task packs, the Parent baseline, solve prompts with `--library`, paired comparison |
| `library establish-parent` | First-write the Parent library snapshot (solidify cannot reach it) |
| `episode list\|show` | Episode records — the runtime-held record of one self-improvement round |
| `exec` `distill` `fetch` `reuse` `publish` `sync` `asset-log` `replay` `rebuild-views` | Execute bridge, distil LLM output, Hub fetch/reuse/publish, asset call log, SQLite replay, derived views |
| `skill2recipe` | Compose verified Skills into a publishable GEP Recipe |
| `mcp` | Run the MCP server over stdio (swarm entry point) |
| `hitl list\|approve\|reject` | HITL approval gate |
| `supervise status\|pause\|resume\|direct\|veto\|unveto` | HOTL supervision |
| `skills list\|scan\|sync` | Skill ecosystem bridge |
| `workflow run\|templates\|status\|awaiting\|approve\|reject\|complete\|resume` | Durable workflow engine |
| `experiment --ablation …` | Controlled experiment / ablation adjudication |
| `webui` `login` `logout` `webui-token` `reset-local-secret` `setup-hooks` `trajectory` | Dashboard, OAuth, tokens, IDE hooks, trace→trajectory export |
| `atp` `atp-complete` `buy` `orders` `verify` | ATP local settlement, auto-buyer consent, ordering |
| `proxy` `proxy-token` | A2A proxy server and local bearer token |
| `recipe list\|show\|apply\|cache-list\|cache-clear` | Recipe Hub |

Every subcommand accepts `--help` for its full flag set.

## Project Structure

```
src/evolver/
├── cli.py              # CLI entrypoint (argparse), .env loading, dispatch
├── config.py           # Runtime thresholds + environment variables
├── canary.py           # Fork-canary: verify CLI loads without crash
├── swarm.py            # Swarm core: takeover instrument prompt + loop tools
│                       #   (tick/distill/hypothesis/propose/solidify/feedback/
│                       #    report/status/supervise/hooks/hook_event/skills),
│                       #   stdout-captured
├── mcp_server.py       # MCP stdio server: 8 general + 18 swarm tools,
│                       #   evolver_swarm prompt, evolver://* resources,
│                       #   tool annotations (mcp>=2.0 MCPServer)
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
│   ├── feedback.py     # Unified evaluation signal E (EvoX harvest)
│   ├── hitl.py         # HITL approval gate (fail-safe to REJECT)
│   ├── supervision.py  # HOTL overlay (pause/veto/directive + tripwire)
│   ├── skill_assets.py # SKILL.md bridge (project > user > builtin)
│   ├── episode_record.py   # Episode records: the runtime-held record of one round
│   ├── evolution_session.py# Paired session machine (§5.1) + one-hypothesis gate
│   ├── library.py      # Content-addressed library snapshots (the scored object)
│   ├── bench/          # Frozen task packs, scoring, frozen gate, paired tests
│   ├── validator/      # Sandbox executor, reporter, stake bootstrap
│   └── ...             # 100+ modules
├── proxy/              # Local HTTP proxy (CLI default 127.0.0.1:8081; routes under /v1/a2a)
│   ├── server/routes.py    # FastAPI route matrix (task/ATP/extensions)
│   ├── router/             # LLM routing, features, SSE streaming
│   ├── extensions/         # DM, session, skill updater, trace control
│   ├── mailbox/store.py    # Local mailbox JSONL storage
│   ├── sync/               # Bidirectional Hub sync engine
│   └── lifecycle/manager.py# Proxy lifecycle + heartbeat
├── atp/                # Agent Transaction Protocol marketplace
│   ├── protocol.py         # Enums and Pydantic models
│   ├── auto_buyer.py       # Auto-discover capability gaps (opt-in, budgeted)
│   ├── auto_deliver.py     # Auto-claim and deliver tasks
│   └── settlement.py       # Local ledger
├── adapters/           # IDE integration hooks
│   ├── hook_adapter.py     # Shared adapter logic
│   ├── setup_hooks.py      # Install hooks for Cursor, Claude Code, Codex, Kiro, OpenCode
│   └── scripts/            # Runtime scripts (session_start, signal_detect)
├── ops/                # Operations (lifecycle, health, self-repair, soak env)
│   ├── lifecycle.py        # Cross-platform daemon management
│   ├── health_check.py     # Disk/memory/process checks
│   └── self_repair.py      # Git emergency repair
├── bench/              # Workspace benchmarks (health tasks + fitness ledger)
├── experiment/         # Controlled experiments, real-LLM ablation, placebo arm, metrics
├── recipe/             # Recipe Hub (list/show/apply + cache)
├── solo/               # Constrained-wild offline mode (hard-cuts network/ATP/validator)
└── webui/              # FastAPI read-only dashboard
    ├── app.py            # Dashboard + SSE `/events/stream`
    ├── dashboard.py      # Self-contained dark HTML dashboard (live events)
    ├── client/           # Inline JS/CSS (SSE, bootstrap, i18n)
    └── observer/         # Data aggregation modules

tests/                  # 342 test files, 4,227 tests (pytest; incl. MCP protocol
                        #   E2E + live-LLM loop E2E under tests/e2e/)
scripts/                # 23 CLI helper scripts (see Scripts section)
src/evolver/assets/gep/ # Seed gene library
memory/                 # Runtime data (graph JSONL, reviews JSONL)
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | Per-user runtime state directory |
| `EVOLVER_REPO_ROOT` | auto-detect | Override repository root |
| `OPENCLAW_WORKSPACE` | (unset) | Workspace root override |
| `GEP_ASSETS_DIR` | `<workspace>/.evolver/gep/` | GEP asset store |
| `EVOLUTION_DIR` | `<workspace>/memory/evolution/` | Evolution state |
| `EVOLVER_SESSION_SCOPE` | (unset) | Per-project state isolation segment |
| `EVOLVE_STRATEGY` | `balanced` | Evolution strategy preset |
| `EVOLVE_BRIDGE` | auto | Git worktree mutation bridge |
| `EVOLVER_ROLLBACK_MODE` | `stash` | Rollback strategy: stash / hard / none |
| `EVOLVER_MAX_CYCLES_PER_PROCESS` | `0` (unlimited) | Max cycles per daemon process |
| `EVOLVER_CYCLE_TIMEOUT_MS` | `2700000` | Hard timeout for a single cycle |
| `EVOLVER_VALIDATOR_ENABLED` | opt-in (`1`/`true` to enable) | Validator daemon |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI port |
| `EVOLVER_PROXY_PORT` | `8081` | Local proxy port (`EVOMAP_PROXY_PORT` alias); override with `evolver proxy --port` |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | auto-generated | Node identity |
| `GITHUB_TOKEN` | — | GitHub API token |
| `EVOLVER_HITL_MODE` | `off` | HITL approval gate — `on` blocks high-risk solidify pending human approval (off still audits; unknown values fail closed to `on`) |
| `EVOLVER_HITL_TTL_MS` | `1800000` | HITL pending-request TTL — expiry fail-safes to REJECT |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL tripwire — auto-pause after N consecutive degraded feedbacks (`0` disables) |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | Swarm feedback degraded threshold — below it (or `success=false`) injects repair-bias |
| `EVOLVER_ADAPTIVE_MUTATION` | `true` | Feedback-driven adaptive mutation-category weights (degraded→repair, plateau→novelty) |
| `EVOLVER_ADAPTIVE_MUTATION_SHIFT` | `0.2` | Adaptive weight shift magnitude (pre-normalization) |
| `EVOLVER_SWARM_AUTO_HIJACK` | `false` | `1` forces HITL on and blocks host-relayed approvals. Standing instructions do not change |
| `EVOLVER_SWARM_GATE_HANDOFF` | `human` | Frozen pack or baseline missing: `human` makes boot/tick return `await_human`; `hotl` ticks anyway (the gate still rejects and rolls back, nothing publishes) |
| `EVOLVER_SKILL_ROOTS` | 3-level roots | Skill root override (os.pathsep-separated; order = priority) |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | Acceptance-gate promotion minimum gated samples (the false-kill ceiling 0.1 and interception band 0.05–0.5 are code constants) |
| `EVOLVER_ACCEPTANCE_SHADOW` | `true` | Shadow mode: verdicts are measured, never enforced; flipping it to `0` is a human decision |
| `EVOLVER_FITNESS_GATE_ENFORCE` | off | Roll back `no_improvement` mutations instead of only reporting |
| `EVOLVER_GENE_INERT_BAN_STREAK` | `8` | Consecutive zero-result rounds before an inert gene is banned |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | Applied-gene cooldown window — recent successful solidifies score-penalized in selection |
| `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY` | `0.25` | Cooldown score multiplier (not a ban — sole matches stay selectable) |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl rotation threshold |
| `EVOLVER_MEMORY_GRAPH_RETENTION_COUNT` | `7` | Rotated archives kept (`0` deletes all) |
| `EVOLVER_MEMORY_GRAPH_AUTO_ROTATE` | `true` | Set `false`/`0`/`no` to disable auto rotation |
| `EVOLVER_ROTATE_GZIP_MAX_MB` | `32` | Above this size an archive is renamed only (no gzip — OOM guard) |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | Anti-abuse telemetry mode (`heartbeat`/`off`) |
| `EVOLVER_OUTCOME_REPORT` | `off` | Report reuse outcomes to the Hub for attribution |
| `EVOLVER_REUSE_ATTRIBUTION` | `off` | Reuse attribution mode |
| `EVOLVER_EVAL_WORKTREE_STRICT` | off | Eval worktree failure: `1` fails instead of falling back to the live cwd |
| `EVOLVER_AUTOPOIESIS` / `EVOLVER_AUTOPOIESIS_WRITE` | `1` / `1` | Autopoiesis phase / persist rules and living memory (`0` = dry-run) |
| `EVOLVER_LEARNING_SIGNALS` | `1` | Inject environment learning signals |
| `EVOLVER_LAUNCHER` | `auto` | Re-invocation launcher: `auto` / `uv` / `uvx` / `python` |
| `EVOLVER_LOOP_COMMAND` | (unset) | Full argv override for the daemon loop command |
| `EVOLVER_FF_*` | per-flag | Feature flags (`EVOLVER_FF_ENABLE_RECALL_INJECT`, `_REFLECTION`, `_EXPLORE`, `_CURRICULUM`, `_SKILL_AUTO_UPDATE`, …) — env beats the on-disk flag store |

## Implementation Status

> **Overall** (2026-10-04): package version **1.113.0**. The paired-session gate closed 2026-09-27; no candidate beat Parent on the sealed val. The live charter is the [Evolution Charter](演进方案.md): *experience as evidence*. The exit is a with/without-record ablation; the n=3 synthetic run is indicative only. The acceptance gate stays in shadow. Percentages below are the 2026-09-05 snapshot, not the work list.

| Subsystem | Status | Notes |
|---|---|---|
| **GEP Data Layer** | ~90% | seed genes 11×sha256; solidify direct tests + learning helpers |
| **GEP Cognition** | ~80% | recall/reflection/distill; explore/curriculum flag-gated |
| **Evolution Pipeline** | ~90% | 7 phases + Autopoiesis + hard timeout; applied-gene cooldown (v1.111) |
| **MCP Swarm** | ~97% | takeover loop + E feedback + HITL/HOTL + hooks/skill bridges + workflow tools; dogfood through round-78 |
| **Workflow Engine** | ~90% | WAL durable steps (script/foreach/if/agent/approval/gate); YAML specs + roles + templates (v1.110) |
| **Acceptance Gate** | ~85% | shadow-mode soak + gate-report verdicts; enforcement switch stays human |
| **Proxy Infrastructure** | ~85% | multi-provider, token reuse, path CLI flags, port **8081** |
| **ATP Marketplace** | ~65% | local settlement; Hub commercial E2E pending |
| **IDE Adapters** | ~85% | runtime hooks + py_compile guard + MCP in-process bridge |
| **Ops / Solo** | ~85% | lifecycle, force-update, `--solo` |
| **WebUI** | ~70% | SSR dashboard + GitHub observer |
| **Validator** | ~50% | sandbox framework; prod network isolation pending |
| **Docs / Release** | ~90% | CHANGELOG + version **1.113.0**; multi-OS CI (blocking Windows + anchor suite) |

Live plan: the [Evolution Charter](演进方案.md) and [TODO.md](TODO.md). The wikiskill audit is an archive.

## Examples

| Example | Description |
|---|---|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **Full swarm-evolution loop** — MCP takeover, tick→execute→distill→solidify→feedback, HITL/HOTL operations (`--llm` runs DeepSeek as the real executor; `demo_closed_loop_flash.py` runs the whole closed loop) |
| [`examples/hello-world/`](examples/hello-world/) | Run a single evolution cycle in an isolated workspace |
| [`examples/daemon-loop/`](examples/daemon-loop/) | Continuous daemon, lifecycle management, start/stop/status/log |
| [`examples/proxy-basics/`](examples/proxy-basics/) | A2A Proxy, proxy-token, curl API examples, LLM relay |
| [`examples/ide-hooks/`](examples/ide-hooks/) | Install session hooks for Cursor, Claude Code, OpenCode, Codex |
| [`examples/solo-mode/`](examples/solo-mode/) | Fully isolated offline mode — no Hub, no network |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis self-check, lessons learned, autopoiesis rules |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | Distill → reuse → publish asset lifecycle |
| [`examples/skill2recipe/`](examples/skill2recipe/) | Compose Agent Skills into GEP Recipes |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP buyer/deliver/heartbeat demo with mocked Hub |

## Testing

```bash
# Run all tests
uv run pytest tests/ -q

# Full-coverage swarm E2E (stdio MCP, every tool/resource/prompt + HITL/HOTL flows)
uv run pytest tests/e2e/ -q

# Live-LLM loop E2E — DeepSeek (deepseek-v4-flash) plays the host executor:
# tick → LLM executes the GEP dispatch prompt → distill → feedback → second tick.
# Requires DEEPSEEK_API_KEY in the environment (skips otherwise).
DEEPSEEK_API_KEY=sk-... uv run pytest tests/e2e/ -m llm -q
# Optional: DEEPSEEK_BASE_URL (default https://api.deepseek.com), DEEPSEEK_MODEL
# (default deepseek-v4-flash)

# Run with coverage
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# Run excluding slow tests (CI default)
uv run pytest -m "not slow"

# Lint + format check + type check
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src

# Validate all module imports
python scripts/validate_modules.py
```

## Scripts

| Script | Purpose |
|---|---|
| `scripts/a2a_export.py` | Export assets to A2A JSON |
| `scripts/a2a_ingest.py` | Import A2A assets |
| `scripts/a2a_promote.py` | Promote candidate gene to active store |
| `scripts/analyze_by_skill.py` | Per-skill evolution event analysis |
| `scripts/baseline_snapshot.py` | Snapshot a baseline for comparison |
| `scripts/build_binaries.py` | PyInstaller standalone build helper |
| `scripts/check_changelog.py` | CHANGELOG vs pyproject version check |
| `scripts/env_inventory.py` | Environment inventory report |
| `scripts/extract_log.py` | Filter events.jsonl by time/type |
| `scripts/generate_history.py` | GEP events timeline (Markdown) |
| `scripts/gep_append_event.py` | Manually append GEP events |
| `scripts/gep_personality_report.py` | Personality HTML report |
| `scripts/harness_governance_check.py` | Harness governance audit |
| `scripts/human_report.py` | Generate Markdown evolution report |
| `scripts/recall_verify_report.py` | Recall/memory-graph coverage |
| `scripts/recover_loop.py` | Daemon loop recovery diagnostics |
| `scripts/seed_merchants.py` | Seed ATP merchant service definitions |
| `scripts/self_ab_acceptance.py` | Self A/B acceptance helper |
| `scripts/soak_env.py` / `scripts/soak_sprint24.py` | Soak environment helpers |
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
- **Episode record** — The runtime-held record of one self-improvement round; the evidence source the ablation adjudicates on
- **ATP** — Agent Transaction Protocol for autonomous service marketplace

## Differences from the Node.js Reference

- **License**: the Python port is licensed under **Apache-2.0** (clean-room behavioral re-implementation based on published APIs, test contracts, and specifications); the upstream Node.js reference implementation is distributed under GPL-3.0-or-later.
- **Source visibility**: the Python port is fully readable and documented; Node.js core files are obfuscated.
- **Database**: the Python port adds `ops/sqlite_store.py` for SQLite persistence (enhancement).
- **Recipe Hub**: the Python port includes the `recipe/` module (new feature).
- **WebUI frontend**: the Python port ships an inline JS client (`webui/client/`) with SSE; not a separate SPA build.
- **Controlled experimentation**: the Python port includes the `experiment/` module for rigorous with/without-records ablation with placebo control and sample-size gating.

## Security Model

Evolver operates with filesystem and network access. Guardrails are enforced at multiple layers:

### Preflight Guards (per-cycle)
- **Self-repair**: auto-fixes stale `.git/index.lock` and pending rebase/merge before each cycle
- **System load**: cycles are skipped when CPU load exceeds `EVOLVE_LOAD_MAX` (default: 0.9× cores for single-core, 1.5× for multi-core)
- **Repair loop circuit breaker**: consecutive failed repair cycles trip degraded mode (repair-only, no innovation) or hard abort
- **User lock**: prevents mutation during active IDE sessions (`~/.evolver/user.lock` with TTL)
- **Release window**: skips evolve near `chore(release)` commits to avoid merge conflicts

### Blast Radius Constraints
- Every Gene declares `constraints.max_files` (typical: 4–20) and `forbidden_paths` (`.git`, `node_modules`, `.venv`)
- A2A blast-radius gate: `A2A_MAX_FILES=5`, `A2A_MAX_LINES=200` (prevents sprawling changes from Hub-fetched assets)
- `EVOLVER_ROLLBACK_MODE=stash` stashes before applying mutations; can rollback on failure

### Content Integrity
- Every asset has a `sha256:` content hash in `asset_id`; loading silently skips hash-mismatched entries
- Seed genes include `asset_id` hashes for tamper-evident baseline
- `sanitize.py` strips dangerous fields from Hub-fetched assets before storage

### Network Safety
- **Proxy**: only listens on `127.0.0.1` by default; `--host 0.0.0.0` is explicit opt-in
- **Hub**: all A2A communication uses node secret signing; `EVOLVER_ANTI_ABUSE_TELEMETRY=heartbeat` for abuse detection
- **Token management**: `webui-token` mints JWTs; WebSocket commands require admin role

### User Secrets
- `redact.py` strips bearer tokens, API keys, JWTs, and passwords from interaction logs
- `.env` files and credentials are never staged or committed by git-commit genes
- Session transcripts are redacted before WebUI display

### Swarm Safety: HITL + HOTL (v1.100–v1.101)
The autonomy spectrum is enforced by two orthogonal gates over the MCP swarm loop:

- **HITL (human-in-the-loop)** — per-decision blocking: `swarm_solidify(skip_validation=true)` is high-risk and passes `gep/hitl.py` (`EVOLVER_HITL_MODE=on` blocks until `evolver hitl approve`; TTL expiry fails safe to REJECT; approvals are idempotent per subject — a rejected run cannot re-request; mode `off` still journals every decision for audit)
- **HOTL (human-on-the-loop)** — supervisory overlay: `gep/supervision.py` pause/resume (tick refuses new cycles), veto substring patterns (ticked gene → dispatch prompt withheld; solidify subject → blocked — defense in depth), steering directives (injected as next-cycle signals), and a tripwire that auto-pauses after N consecutive degraded feedback reports
- All supervision/approval actions are journaled (`supervision_events.jsonl`, `hitl_approvals.jsonl`)

## Anti-Examples (Things That Won't Work)

| Don't | Why |
|-------|-----|
| Run evolver from `/tmp` without a git repo | Genes rely on git for blast-radius tracking and rollback |
| Set `OPENCLAW_WORKSPACE` to a production server | Evolver applies code mutations — use an isolated workspace |
| Enable `--loop` without a Hub connection or seed genes | The gene pool depletes; set `EVOLVER_GENE_INERT_BAN_STREAK` high |
| Run multiple evolver instances on the same workspace | Instance locks prevent this; use `EVOLVER_SESSION_SCOPE` for per-project isolation |
| Expect immediate results from `--solo` mode | Solo mode has no Hub assets; build your gene pool over many cycles |
| Use `--review` in CI/CD pipelines | Review mode blocks on stdin; use `--loop` for automated runs |
| Mix Node.js and Python evolver instances on the same repo | State file formats differ; migrate fully to one implementation |
| Set `EVOLVER_AUTOPOIESIS_WRITE=1` then check `LESSONS_LEARNED.md` immediately | Lessons are written asynchronously after cycle completion |
| Grade a candidate on the same context that wrote it | The paired-session and bench rules require val solves in a separate context |

## Hub Connection

The Hub (`A2A_HUB_URL`, default: `https://evomap.ai`) provides:

- **Asset discovery**: gene/capsule search via `GET /api/assets` or `evolver fetch <query>`
- **Task marketplace**: list, claim, and complete tasks via `evolver sync` or proxy endpoints
- **ATP settlement**: order placement, delivery verification, dispute resolution
- **Event sync**: bidirectional event delivery using SSE + poll with exponential backoff on failure

Connection is fully optional — `--solo` mode disables all Hub features. The proxy manages connection lifecycle:
- `hello` heartbeat on startup (multi-phase with retry)
- Exponential backoff on Hub unreachable (1s → 30s cap)
- Anti-abuse telemetry heartbeat (configurable via `EVOLVER_ANTI_ABUSE_TELEMETRY`)
- Node key versioning (`A2A_NODE_SECRET_VERSION`) for secret rotation

To connect to a custom Hub:

```bash
A2A_HUB_URL=https://your-hub.example.com uv run evolver proxy
```

## Documentation

- [Evolution Charter](演进方案.md) — Current charter (Chinese)
- [TODO.md](TODO.md) — Work list for that charter
- [CHANGELOG.md](CHANGELOG.md) — Per-round notes (v1.98 through round-99; current release 1.113.0)
- [AGENTS.md](AGENTS.md) — Agent integration guide, coding standards, pitfalls
- [DEBUG.md](DEBUG.md) — Debugging playbook: dogfood and interlock bugs, with root causes and transferable lessons
- [RSI comparison log](RSI演进对照.md) — Archived paper comparison and effective-L5 log (Chinese)
- [Wikiskill audit](演进方案_wikiskill对照版.md) — Archived 2026-09-01 audit (Chinese)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines
- [`SKILL.md`](SKILL.md) — Skill usage reference
- [`docs/env-registry.md`](docs/env-registry.md) — Environment variable registry

## License

Distributed under the [Apache License 2.0](LICENSE).

> **Note on Upstream Lineage**: This project is an independent Python clean-room behavioral re-implementation developed from scratch against documented protocols, test contracts, and public APIs. The original Node.js reference implementation is maintained by EvoMap under GPL-3.0-or-later. This project is released under Apache-2.0.
