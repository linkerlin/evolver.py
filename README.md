# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**A GEP-powered self-evolution engine for AI agents.**

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
# Install dependencies (project-local env)
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

**让宿主 Agent 加入蜂群（v1.98+ 的旗舰能力）**——引擎经 MCP stdio 接管宿主为进化执行器，一条命令体验完整闭环：

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py   # 或加 --llm 用 DeepSeek 真执行
```

详见 [MCP Swarm Evolution](#mcp-swarm-evolution蜂群进化) 与 [examples/swarm-quickstart/](examples/swarm-quickstart/)。

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

## MCP Swarm Evolution（蜂群进化）

evolver 通过 stdio MCP server 把**宿主 Agent 变成 GEP 变异提示词的执行器**——引擎不自建 LLM API 调度，连接进来的宿主（ZCode / Claude Code / Cursor / …）即执行器（v1.98.0+）。

### 宿主接入配置

启动命令二选一：`uv run evolver mcp`（项目内）或 `<venv>/bin/python -m evolver.mcp_server`（绝对路径，推荐给宿主配置）。

**ZCode**（工作区/用户级 settings 的 `mcpServers`）：

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

**Claude Code**（项目根 `.mcp.json`）与 **Cursor**（`.cursor/mcp.json`）同构：

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

> 常用环境变量：`EVOLVER_SWARM_AUTO_HIJACK=1`（instructions 直接注入接管指令，无人值守模式）；`EVOLVER_HITL_MODE=on`（高危 solidify 需人类批准）；`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`（连续降级反馈自动暂停，默认 3）。

### 接管与闭环

- **注入双通道**：MCP prompt `evolver_swarm`（正式 instrument，宿主经 prompts 渲染）+ `swarm_boot` 工具（覆盖不渲染 prompt 的宿主）
- **闭环协议**：`swarm_tick`（取 GEP 变异提示词）→ 宿主用自己的编辑工具执行变异 → `swarm_distill`（蒸馏 Gene/Capsule）→ `swarm_solidify`（验证门 + 固化）→ `swarm_feedback`（统一评估信号 E，低分自动注入 repair-bias）→ 循环
- **安全双闸**：HITL 审批门（`evolver hitl list|approve|reject`，超时 fail-safe 拒绝）+ HOTL 监督（`evolver supervise status|pause|resume|direct|veto|unveto`，人在环上随时刹车/否决/转向）

### Hooks 集成（信号自动采集）

宿主支持 hooks 时安装文件钩子，session 边界与工具输出中的错误信号自动进入进化记忆：

```bash
uv run evolver setup-hooks --platform auto --project-dir /path/to/workspace
# 平台：cursor | claude-code | codex | kiro | opencode | vscode | generic | auto
```

MCP-only 宿主（无文件 hooks 能力）改用**进程内桥**：在会话开始/结束、以及观察到错误输出时调用 `swarm_hook_event` 工具（`event=session_start|session_end|signal_detect`，`payload.content` 携带文本）；检测到的信号（`log_error` / `perf_bottleneck` / …）直接注入下一进化周期的基因选择。也可经 `swarm_hooks` 工具（`action=status|install|uninstall`）由宿主自助安装文件钩子。

### MCP Resources 与工具注解

除工具外，server 暴露四个只读资源（宿主可订阅/免工具往返读取）：

| URI | 内容 |
|---|---|
| `evolver://status` | 实时引擎/蜂群状态（JSON，含 HITL/HOTL/反馈摘要） |
| `evolver://instrument-prompt` | 当前渲染的接管提示词 |
| `evolver://dispatch/last` | 最近一次 GEP 变异提示词（`last_prompt.md`） |
| `evolver://events/recent` | 最近进化周期时间线（JSON） |

工具带 MCP 规范注解：`swarm_status` / `swarm_approvals` / `asset_search` 等标记 `readOnlyHint`（宿主计划模式可安全跳过确认）；`swarm_solidify` 标记 `destructiveHint`（宿主可要求用户确认）。

### 技能生态桥（SKILL.md → 技能基因）

把宿主生态的技能文件接入进化引擎（EvoX SkillRegistry 模式：**project > user > builtin 三级优先、同名遮蔽**）。发现根目录：工作区 `.agents/skills` 与 `.claude/skills` > 用户 `~/.agents/skills`、`~/.zcode/skills`、`~/.claude/skills` > 引擎内置（可用 `EVOLVER_SKILL_ROOTS` 覆盖，顺序即优先级）。

```bash
uv run evolver skills scan              # 预览发现（含优先级与遮蔽）
uv run evolver skills sync --dry-run    # 预览将安装的技能基因
uv run evolver skills sync              # 转换并入 GEP 资产库（gene_distilled_s2g-*）
uv run evolver skills list              # 查看库中技能基因
```

同步后，技能以基因身份参与信号匹配与选择——例如一个「修复 ImportError」技能会在信号命中时被选入 GEP 提示词。宿主也可经 MCP `swarm_skills` 工具（`scan|list|sync`）自助操作。

### 进化工作流（EvoX 收割：协作即数据）

一整段协作表达为一份 **YAML 工作流**（可 diff → 可进化）：`agent` 步骤声明 `role`/`instruction` 等宿主执行器认领，`gate` 步骤引擎侧直跑验证级联（ruff→mypy→pytest），`approval` 步骤落人类审批门——全程 WAL 持久化、断点续跑（Sprint 24.10 引擎 + v1.110.0 扩展）。

```bash
uv run evolver workflow templates                  # 捆绑模板：repair / innovate
uv run evolver workflow run --template repair      # 启动修复回路（也可给 YAML 文件）
uv run evolver workflow awaiting <id>              # 宿主执行器/审批者当前待办
uv run evolver workflow complete <id> --result '{"ok": true, "files": 2}'
uv run evolver workflow approve <id>               # 审批放行
```

MCP 侧：`swarm_workflow_run`（文件或模板启动）、`swarm_workflow_act`（approve/reject/complete/resume/cancel）、`swarm_workflow_status`（全量状态 + 宿主待办）。

> WebUI / Proxy 需要 server extras：`uv sync --extra server`（核心进化引擎与 MCP server 无 fastapi 依赖）。

## Prerequisites

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — Required. Evolver uses git for rollback, blast radius calculation, and solidify. Running in a non-git directory will fail with a clear error message.
- **[uv](https://docs.astral.sh/uv/)** — Recommended. Enables `uv sync`, `uv run`, and `uvx`. Standard `pip` / `python -m` also work.

## Project Structure

```
src/evolver/
├── cli.py              # CLI entrypoint
├── config.py           # Environment variables + thresholds
├── canary.py           # Fork-canary: verify CLI loads without crash
├── swarm.py            # Swarm core: takeover instrument prompt + loop tools
│                       #   (tick/distill/solidify/feedback/report/status/
│                       #    supervise/hooks/hook_event/skills), stdout-captured
├── mcp_server.py       # MCP stdio server: swarm + asset/mailbox tools,
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
│   ├── validator/      # Sandbox executor, reporter, stake bootstrap
│   └── ...             # 60+ modules
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

tests/                  # 280+ test files, 3455+ tests (pytest; incl. MCP
                        #   protocol E2E + live-LLM loop E2E under tests/e2e/)
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
| `EVOLVER_HITL_MODE` | `off` | HITL approval gate — `on` blocks high-risk solidify pending human approval (off still audits) |
| `EVOLVER_HITL_TTL_MS` | `1800000` | HITL pending-request TTL — expiry fail-safes to REJECT |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL tripwire — auto-pause after N consecutive degraded feedbacks (`0` disables) |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | Swarm feedback degraded threshold — below it (or `success=false`) injects repair-bias |
| `EVOLVER_ADAPTIVE_MUTATION` | `true` | Feedback-driven adaptive mutation-category weights (degraded→repair, plateau→novelty) |
| `EVOLVER_ADAPTIVE_MUTATION_SHIFT` | `0.2` | Adaptive weight shift magnitude (pre-normalization) |
| `EVOLVER_SKILL_ROOTS` | 3-level roots | Skill root override (os.pathsep-separated; order = priority) |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | Acceptance-gate promotion minimum gated samples |
| `EVOLVER_GATE_SOAK_MAX_FALSE_KILL` | `0.1` | False-kill ceiling for promotion verdict `ready` |
| `EVOLVER_GATE_SOAK_INTERCEPT_MIN` / `_MAX` | `0.05`/`0.5` | Interception-rate band for promotion |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | Applied-gene cooldown window — recent successful solidifies score-penalized in selection |
| `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY` | `0.25` | Cooldown score multiplier (not a ban — sole matches stay selectable) |
| `EVOLVER_HUB_FETCH_RETRIES` | `1` | Hub fetch retry count (exponential backoff; living-memory f001) |
| `EVOLVER_HUB_FETCH_RETRY_BACKOFF_MS` | `500` | Hub fetch retry backoff base |
| `EVOLVER_SWARM_AUTO_HIJACK` | `false` | `1` injects takeover instructions directly into MCP server instructions |
| `EVOLVER_FF_ENABLE_RECALL_INJECT` | `true` | Inject verified recall hints into GEP prompt |
| `EVOLVER_FF_ENABLE_REFLECTION` | `true` | Tune personality after solidify |
| `EVOLVER_FF_ENABLE_EXPLORE` | `false` | AST-based codebase exploration signals |
| `EVOLVER_FF_ENABLE_CURRICULUM` | `false` | Progressive curriculum task sequencing |
| `EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE` | `false` | Proxy skill updater background loop |

## Implementation Status

> **Overall** (2026-09-05): package version **1.111.0**. The MCP swarm stack
> (v1.98–v1.111: takeover loop, evaluation feedback E, HITL/HOTL safety,
> hooks bridge, skill bridge, feedback-adaptive mutation, acceptance-gate
> soak, YAML workflow engine with role nodes + cascade gates) is complete and
> green (**3455 tests passing**, mypy strict 0 errors). Five dogfood rounds
> ran the full loop on this repo itself — 4 gated runs accumulated on the
> acceptance gate (verdict honestly `collecting`, needs ≥20). Node-parity
> baseline v1.94.0 retained; remaining depth gaps: [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md).

| Subsystem | Status | Notes |
|---|---|---|
| **GEP Data Layer** | ~90% | seed genes 11×sha256; solidify direct tests + learning helpers |
| **GEP Cognition** | ~80% | recall/reflection/distill; explore/curriculum flag-gated |
| **Evolution Pipeline** | ~90% | 7 phases + Autopoiesis + hard timeout; applied-gene cooldown (v1.111) |
| **MCP Swarm** | ~97% | takeover loop + E feedback + HITL/HOTL + hooks/skill bridges + workflow tools (run/act/status); 5 dogfood rounds live |
| **Workflow Engine** | ~90% | WAL durable steps (script/foreach/if/agent/approval/gate); YAML specs + roles + templates (v1.110) |
| **Acceptance Gate** | ~85% | shadow-mode soak + gate-report verdicts; enforcement switch stays human |
| **Proxy Infrastructure** | ~85% | multi-provider, token reuse, path CLI flags, port **8081** |
| **ATP Marketplace** | ~65% | local settlement; Hub commercial E2E pending |
| **IDE Adapters** | ~85% | runtime hooks + py_compile guard + MCP in-process bridge |
| **Ops / Solo** | ~85% | lifecycle, force-update, --solo |
| **WebUI** | ~70% | SSR dashboard + GitHub observer |
| **Validator** | ~50% | sandbox framework; prod network isolation pending |
| **Docs / Release** | ~90% | CHANGELOG + version **1.111.0**; multi-OS CI advisory |

See [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) for the live gap roadmap.

## Examples

| Example | Description |
|---|---|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **蜂群进化全闭环**——MCP 接管、tick→执行→distill→solidify→feedback、HITL/HOTL 运维（支持 `--llm` 由 DeepSeek 真实执行） |
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

## Security Model

Evolver operates with filesystem and network access. Guardrails are enforced at multiple layers:

### Preflight Guards (per-cycle)
- **Self-repair**: Auto-fixes stale `.git/index.lock` and pending rebase/merge before each cycle
- **System load**: Cycles are skipped when CPU load exceeds `EVOLVE_LOAD_MAX` (default: 0.9× cores for single-core, 1.5× for multi-core)
- **Repair loop circuit breaker**: Consecutive failed repair cycles trip degraded mode (repair-only, no innovation) or hard abort
- **User lock**: Prevents mutation during active IDE sessions (`~/.evolver/user.lock` with TTL)
- **Release window**: Skips evolve near `chore(release)` commits to avoid merge conflicts

### Blast Radius Constraints
- Every Gene declares `constraints.max_files` (typical: 4–20) and `forbidden_paths` (`.git`, `node_modules`, `.venv`)
- A2A blast-radius gate: `A2A_MAX_FILES=5`, `A2A_MAX_LINES=200` (prevents sprawling changes from Hub-fetched assets)
- `EVOLVER_ROLLBACK_MODE=stash` stashes before applying mutations; can rollback on failure

### Content Integrity
- Every asset has a `sha256:` content hash in `asset_id`; loading silently skips hash-mismatched entries
- Seed genes now include `asset_id` hashes for tamper-evident baseline
- `sanitize.py` strips dangerous fields from Hub-fetched assets before storage

### Network Safety
- **Proxy**: Only listens on `127.0.0.1` by default; `--host 0.0.0.0` is explicit opt-in
- **Hub**: All A2A communication uses node secret signing; `EVOLVER_ANTI_ABUSE_TELEMETRY=heartbeat` for abuse detection
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
| Run multiple evolver instances on the same workspace | File locks prevent this; use `EVOLVER_SESSION_SCOPE` for per-project isolation |
| Expect immediate results from `--solo` mode | Solo mode has no Hub assets; build your gene pool over many cycles |
| Use `--review` in CI/CD pipelines | Review mode blocks on stdin; use `--loop` for automated runs |
| Mix Node.js and Python evolver instances on the same repo | State file formats differ; migrate fully to one implementation |
| Set `EVOLVER_AUTOPOIESIS_WRITE=1` then check `LESSONS_LEARNED.md` immediately | Lessons are written asynchronously after cycle completion |

## Hub Connection

The Hub (`A2A_HUB_URL`, default: `https://evomap.ai`) provides:

- **Asset discovery**: Gene/capsule search via `GET /api/assets` or `evolver fetch <query>`
- **Task marketplace**: List, claim, and complete tasks via `evolver sync` or proxy endpoints
- **ATP settlement**: Order placement, delivery verification, dispute resolution
- **Event sync**: Bidirectional event delivery using SSE + poll with exponential backoff on failure

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

- [`CHANGELOG.md`](CHANGELOG.md) — Release history (v1.98–v1.105 swarm arc)
- [`设计方案.md`](设计方案.md) — Comprehensive design document (Chinese, ~1500 lines)
- [`TODO.md`](TODO.md) — Detailed gap analysis and roadmap
- [`AGENTS.md`](AGENTS.md) — Agent integration guide, coding standards, pitfalls
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines
- [`SKILL.md`](SKILL.md) — Skill usage reference

## License

[Apache License 2.0](LICENSE)

> This is a community port of the EvoMap evolver engine. The original Node.js reference implementation is distributed by EvoMap under GPL-3.0-or-later.
