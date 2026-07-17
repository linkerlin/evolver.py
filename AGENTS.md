# AGENTS.md — evolver.py

> 以 GEP 为驱动之 AI 智能体自进化引擎。

## 命令篇

| 操作 | 命令 |
|---|---|
| 安装依赖 | `uv sync` |
| 运行一进化周期 | `uv run evolver`（或 `uv run evolver run`） |
| 守护进程循环 | `uv run evolver --loop` |
| 审查模式 | `uv run evolver --review` |
| 应用待定变异 | `uv run evolver solidify` |
| Autopoiesis 自检 | `uv run evolver self-report [--no-write] [--json]` |
| 蒸馏 LLM 响应 | `uv run evolver distill --response-file=<path>` |
| 从 Hub 获取技能 | `uv run evolver fetch <query>` |
| 同步资源 | `uv run evolver sync [--scope=...]` |
| 启动 WebUI | `uv run evolver webui [--port=8080]` |
| 启动本地代理 | `uv run evolver proxy [--port=8081]` |
| 守护进程生命周期 | `uv run evolver start` / `stop` / `restart` / `status` / `log` |
| 健康检查 | `uv run evolver check` / `watch` |
| Recipe Hub | `uv run evolver recipe list|show|apply|…` |
| 运行测试 | `uv run pytest` |
| 运行测试（排除慢速） | `uv run pytest -m "not slow"` |
| 代码检查 | `uv run ruff check src tests` |
| 格式检查 | `uv run ruff format --check src tests` |
| 自动格式化 | `uv run ruff format src tests` |
| 类型检查 | `uv run mypy src` |
| 通过 python 运行 | `uv run python -m evolver` |

## 架构篇

此乃 **从 Node.js 移植**之作也。原代码 `@evomap/evolver` 为 `javascript-obfuscator` 重度混淆，不可直读。Python 实现乃基于测试契约与公开 API 表面之**行为等价重实现**，非逐行翻译者也。

### 源码布局（`src/evolver/`）

```
cli.py              CLI 入口（argparse）、.env 加载、命令分发
config.py           全部运行时阈值/超时、环境变量覆盖
canary.py           Fork-canary：验证 CLI 加载不出崩溃
gep/                GEP（基因组进化协议）核心
  schemas/          Pydantic 模型：Gene、Capsule、Task、Protocol
  asset_store.py    JSON/JSONL 持久化，叠加语义（生产级）
  paths.py          中心化路径解析，支持环境变量覆盖
  a2a_protocol.py   Agent 间 Hub 协议（HTTP）
  bridge.py         Git worktree 变异桥接
  content_hash.py   SHA-256 内容寻址资源 ID
  crypto.py         本地密钥管理
  distill.py        从 LLM 文本输出中提取 Gene/Capsule
  fetch.py          从 Hub 下载并安装资源
  git_ops.py        Git diff/回滚/状态辅助函数
  instance_lock.py  基于 FileLock 之单实例守护
  memory_graph.py   JSONL 记忆图谱存储与信号键查询
  cognition.py      高级认知编排：recall/explore/curriculum/reflection/distill 接线
  mutation.py       变异引擎：类别选择、变体生成
  personality.py    人格配置文件（严谨度、风险容忍度）
  prompt.py         GEP 提示词组装
  sanitize.py       资源字段输入净化
  selector.py       Gene/Capsule 与信号匹配（含 living_memory 评分调节）
  signals.py        信号收集与分类
  solidify.py       应用基因 → 验证 → 持久化 → 发布
  autopoiesis.py    Autopoiesis 编排（SelfReport + homeostasis + viability）
  self_report.py    摩擦捕获 → autopoiesis_rules.json + LESSONS_LEARNED.md
  living_memory.py  活记忆加载（LESSONS_LEARNED YAML frontmatter）
  memory_bridge.py  living_memory ↔ memory_graph ↔ signals 桥接
  autopoiesis_rules.py  guard 规则 → pending/autopoiesis 信号
  learning_signals.py   平台/依赖环境学习信号
  strategy.py       进化策略选择
  sync.py           Hub 同步：获取任务、下载资源
  validator/        验证者守护进程（文件存在，安全模型待完善）
evolve/             进化流水线
  runner.py         编排器：单周期 + 守护循环
  guards.py         起飞前检查（负载、RSS、冷却）
  pipeline/         七阶段流水线 + preflight + post_cycle（各为 async 函数，取/返 ctx）
    collect.py      扫描 memory/ 之运行时日志与错误模式
    signals.py      从收集数据中分类信号
    hub.py          向 Hub 查询匹配之资源与任务
    enrich.py       以 Hub 数据丰富上下文 + 认知蒸馏/回忆 + living_memory 桥接
    autopoiesis.py  SelfReport / homeostasis（enrich 之后、select 之前）
    select.py       选择最佳 Gene/Capsule（repair bias + innovation 记录）
    dispatch.py     生成 GEP 提示词（含回忆 + autopoiesis_context），写入分发输出
  post_cycle.py     周期末钩子（ATP auto-buyer、task pickup）
proxy/              本地 HTTP 代理（CLI 默认 127.0.0.1:8081；路由前缀 /v1/a2a）
  mailbox/store.py  本地邮箱 JSONL 存储（较完整）
  sync/             双向同步引擎（较完整）
  lifecycle/        生命周期管理器（hello/heartbeat + ATP 信号处理 + 节点密钥版本化 +
                    Hub 不可达指数退避 + 反滥用遥测心跳 + 心跳强制更新 + 最后更新确认）
  server/routes.py  FastAPI 路由矩阵（task/ATP/extensions/asset/validate 已接线）
  router/           模型路由/特性路由/缓存透传/messages_route（含 Anthropic/Bedrock SSE）
  extensions/       DM/会话/技能更新/追踪控制 + SkillUpdateLoop + AtpDeliverLoop
  task/monitor.py   任务监控（已接入 routes）
  trace/store.py    请求追踪环形缓冲（Hub 转发诊断）
webui/              FastAPI 只读仪表盘
  server/http.py    `create_app()` 统一工厂 + `WebUiServer` 嵌入式服务
  app.py            向后兼容：`app = create_app()`
  dashboard.py      暗色 HTML 仪表盘（实时事件表）
  observer/         数据聚合模块（已实现）
  client/           内嵌 JS/CSS（sse、bootstrap、i18n、static）
ops/                健康检查、清理、叙事日志
  lifecycle.py      跨平台守护进程管理（较完整）
  health_check.py   系统健康检查（较完整）
  self_repair.py    Git 紧急修复
  cleanup.py        日志与产物清理
  narrative.py      叙事日志
  sqlite_store.py   SQLite 持久化增强
  skills_monitor.py 技能健康监控（已实现）
  innovation.py     创新追踪（已实现）
  trigger.py        外部触发器（已实现）
adapters/           IDE 钩子生成器
  hook_adapter.py   共享适配器逻辑（较完整）
  setup_hooks.py    CLI 入口：adapter 平台运行时 hooks + vscode/generic 静态配置
  cursor.py         Cursor hooks.json 适配器
  scripts/          运行时脚本（session_start, signal_detect, session_end 深度有限）
  claude_code.py    Claude Code 适配器（已实现）
  codex.py          Codex 适配器（已实现，功能略少于 Cursor）
  kiro.py           Kiro 适配器（已实现）
  opencode.py       OpenCode 适配器（已实现）
atp/                Agent 交易协议市场
  protocol.py       枚举与 Pydantic 模型（完整）
  hub_client.py     Hub API 客户端（中等）
  auto_buyer.py     自动消费代理（缺口检测 + run_tick + 预算去重）
  auto_deliver.py   自动商家交付（轮询 + default_handler 认领交付）
  consumer_agent.py 消费者代理模板（骨架）
  merchant_agent.py 商家代理模板（骨架）
  settlement.py     本地账本（较完整）
  default_handler.py 默认处理器（已实现）
```

### 数据流（单周期）

```
起飞前检查 → 收集 → 信号 → Hub → 丰富 → Autopoiesis → 选择 → 分发
  ↑ abort 时 SelfReport + 持久化；下周期 signals 注入 preflight_abort + repair bias
                                                   ↓
                                              [GEP 提示词]
                                                   ↓
                                                 固化 → 活记忆 / innovation 反馈
```

上下文为一纯 `dict[str, Any]`，贯穿各流水线阶段。

### GEP 资源存储

位于 `<GEP_ASSETS_DIR>`（默认 `<workspace>/.evolver/gep/`）：

- `genes.json` + `genes.jsonl`——基础 + 叠加层（JSONL 条目按 ID 覆盖）
- `capsules.json` + `capsules.jsonl`——同例
- `events.jsonl`——仅追加之进化事件日志
- `candidates.jsonl`、`external_candidates.jsonl`
- `failed_capsules.json`
- `pending_signals.json`
- `autopoiesis_rules.json`——Autopoiesis guard 规则（摩擦自动编码）

活记忆与自检（`<EVOLUTION_DIR>/`，默认 `memory/evolution/`）：

- `LESSONS_LEARNED.md`——活记忆器官（YAML frontmatter + 摩擦点）
- `self_report.json`——最近自检报告
- `autopoiesis.jsonl`——AutopoiesisTick 追加日志
- `autopoiesis_state.json`——跨周期 Hub 降级标志
- `autopoiesis_preflight_abort.json`——上次 preflight abort 快照（成功周期后清除）
- `memory_graph_state.json`——`preferred_by_signal`、living_memory 摩擦同步元数据
- `innovation_log.jsonl`——创新尝试 ROI 追踪

资源完整性通过存于 `asset_id` 中之 `sha256:` 内容哈希验证之。

## 规范篇

### 代码风格

- 全项目用 Python 3.12+ 语法：`from __future__ import annotations`、`X | None` 联合类型、`list[str]` 泛型
- Pydantic v2 模型配 `ConfigDict(extra="forbid")`——未知字段致验证错误
- 每文件顶部书 `from __future__ import annotations`
- 双引号（`ruff format` 默认）
- 行宽限 100 字符
- 四空格缩进
- 所有 `async` 函数皆为 `async def`，不用 `@asyncio.coroutine`
- 所有公开函数皆有类型注解
- 模块级常量来自配置者，用 `Final`
- 不用 `typing.TypedDict`——流水线上下文用 `dict[str, Any]`，模式用 Pydantic

### 命名

- 模块：`snake_case.py`
- 类：`PascalCase`（Pydantic 模型、dataclasses）
- 函数：`snake_case`
- 常量：`UPPER_SNAKE_CASE`，配 `Final` 类型
- 内部辅助函数：前导下划线 `_helper_fn`
- GEP 术语原样保留：`Gene`、`Capsule`、`solidify`、`dispatch`、`distill`
- 每源文件皆有 docstring，指向其 Node.js 等价物

### 导入模式

- `cli.py` 与 `guards.py` 中刻意用函数内惰性导入，以免在 `.env` 加载之前拉入重型模块
- `config.py` 早导入——其只读取环境变量，无副作用
- 流水线阶段从 `evolver.gep.*` 子模块导入，不互相导入

### 测试

- `pytest` 配 `pytest-asyncio` 之 `"auto"` 模式（无需 `@pytest.mark.asyncio`）
- `respx` 用于 mock `httpx` 调用
- `freezegun` 用于时间相关测试
- 测试文件与源码一一对应：`test_<module>.py` 测试 `evolver.<module>`
- `conftest.py` 中之 `temp_workspace` fixture 隔离所有路径环境变量
- `test_cli.py` 中之 `isolated_evolver_env` fixture 加 `EVOLVER_NO_PARENT_GIT=1`
- 资源存储测试用 `monkeypatch.setenv("GEP_ASSETS_DIR", ...)`
- Git 相关测试用 `subprocess.run(["git", "init", ...])`

### Ruff 规则

全套 lint：`E, F, W, I, N, UP, B, C4, SIM, ARG, PL, RUF`

有意抑制者：
- `PLR2004`——魔法值比较于此移植中颇有裨益
- `PLR0913`——多参数乃继承自 Node API 设计

### mypy

`strict = true`，`ignore_missing_imports = true`，`warn_return_any`，`warn_unused_ignores`。

## 要紧环境变量

测试须隔离此诸项。最重要者：

| 变量 | 默认 | 用途 |
|---|---|---|
| `OPENCLAW_WORKSPACE` | （无） | 工作区根覆盖 |
| `EVOLVER_REPO_ROOT` | 通过 `.git` 自动检测 | 仓库根覆盖 |
| `EVOLVER_HOME` | `~/.evomap` | 每用户状态目录 |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP 资源存储 |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 进化状态 |
| `MEMORY_DIR` | `<ws>/memory/` | 记忆日志 |
| `EVOLVER_NO_PARENT_GIT` | （无） | 设为 `1` 以禁用 `.git` 遍历 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub 端点 |
| `EVOLVE_STRATEGY` | `balanced` | 进化策略 |
| `EVOLVE_BRIDGE` | auto | Git worktree 变异 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | 回滚策略 |
| `EVOLVER_AUTOPOIESIS` | `1` | 启用 Autopoiesis 阶段 |
| `EVOLVER_AUTOPOIESIS_WRITE` | `1` | 持久化规则/活记忆（`0`=dry-run） |
| `EVOLVER_REPAIR_LOOP_DEGRADED` | `1` | repair-loop 降级运行（非硬 abort） |
| `EVOLVER_LEARNING_SIGNALS` | `1` | 注入环境学习信号 |
| `EVOLVER_GENE_INERT_BAN_STREAK` | `8` | 惰性基因禁用阈值——连续 N 次零工作结果后禁选 (#562) |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 反滥用遥测模式（`heartbeat`/`off`，空值视为 heartbeat） |
| `EVOLVER_OUTCOME_REPORT` | `off` | 结果上报模式——向 Hub 上报复用结果以获归因 (P4-a Slice B) |
| `EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS` | `300000` (5min) | Hub 推送强制更新的最小间隔冷却 |
| `A2A_NODE_SECRET_VERSION` | （无） | 节点密钥版本号——Hub 轮换密钥时递增，客户端据此检测陈旧 secret |

## 坑阱篇

- **`.env` 加载次序攸关**：`cli.py:_load_dotenv()` 先加载 cwd 之 `.env`，后加载仓库根之 `.env`。内部导入在其后。若在 `cli.py` 中添加顶层重型模块导入，将破坏环境变量优先级。
- **JSONL 叠加语义**：`genes.jsonl` 条目按 ID 覆盖 `genes.json`。从 `.json` 中删除一基因而未从 `.jsonl` 中删除，将使其复活。须以二文件同测之。
- **内容哈希验证**：`asset_store.load_genes()` 静默跳过 `asset_id` 哈希与内容不符之条目。加载时"消失"之基因，其哈希大概率为损坏者。
- **Windows 无 `os.getloadavg()`**：`guards.py:get_system_load()` 在 Windows 上捕获 `AttributeError` 并返回零。勿于 Windows 测试中依赖负载值。
- **`--mad-dog` 即 `--loop`**：CLI 别名也，非独立模式。
- **`asyncio_mode = "auto"`**：所有 `async def test_*` 自动视为异步测试。无需标记。
- **`from __future__ import annotations`**：所有注解在运行时皆为字符串。勿将注解用于 `isinstance()` 检查。
- **原子写入**：`asset_store.atomic_write_json` 用临时文件 + `os.replace`。在 Windows 上，若目标被另一进程打开（如守护循环），此操作将败。
- **`canary.py` 为子进程运行**：其在 `solidify` 提交之前于子进程中运行。测试中勿直接从中导入。
- **种子数据**：`src/evolver/assets/gep/genes.seed.json` 为捆绑之默认基因。测试不应修改之——用 `GEP_ASSETS_DIR` 覆盖。
- **测试隔离**：环境变量总是用 `monkeypatch.setenv`，勿直接用 `os.environ`。`temp_workspace` fixture 为此常用路径处理之。
- **Proxy 路径前缀**：所有 `routes.py` 路由挂载于 `/v1/a2a`（如 `/v1/a2a/mailbox/send`）。LLM 中继为 `/v1/a2a/v1/messages`。
- **Proxy 端口**：默认 `8081`；`config.resolve_proxy_port()` / `proxy_local_url()` 为统一入口；`EVOLVER_PROXY_PORT` 可覆盖。
- **Proxy 路由深度**：`/task/*`、部分 `/atp/*` 为本地内存状态机，非 Hub 生产级任务流。
- **IDE 双轨**：`setup-hooks` 对 `cursor`/`claude-code`/`codex`/`kiro`/`opencode` 调用各 adapter `install()`；`vscode`/`generic` 仍写静态配置。`--project-dir` 为安装根，不回落 `$HOME`。
- **Feature flags**：`proxy/router/features.py` 委托 `gep/feature_flags.py`；`EVOLVER_FF_*` 对 GEP 与 Proxy 路由同时生效。
- **许可证差异**：本移植使用 Apache-2.0，Node.js 参考实现使用 GPL-3.0-or-later。如引入 Node 版之测试或文档，须注意许可证兼容性。
