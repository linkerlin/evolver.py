# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · **简体中文** · [日本語](README.ja-JP.md) · [한국어](README.ko-KR.md)

**一个基于 GEP（基因组进化协议）的 AI 智能体自进化引擎。**

引擎不自建 LLM 调度。宿主 Agent 经 MCP stdio 充当执行器。本阶段把这个环指向一个冻结的外部任务包，见 [演进方案.md](演进方案.md)（现行章程）。本树是 `@evomap/evolver` 的行为等价 Python 移植，使用现代 Python 工具链：

- **Python 3.12+** — `asyncio`、类型参数语法（`list[str]`）、`tomllib`
- **uv** — 高速 Python 包管理
- **Pydantic v2** — 模式验证与配置
- **httpx** — 异步 HTTP 客户端（相当于 Node.js 的 `undici`）
- **FastAPI + uvicorn** — 本地代理与 WebUI（可选 `server` extra）

> **注意**：GEP 核心、进化流水线、Proxy 路由与认知编排已基本可用。ATP 商业闭环和验证者沙箱仍不完整，它们不在本阶段。

---

## 快速开始

```bash
# 安装依赖（项目内环境）
uv sync

# 运行单次进化周期
uv run evolver

# 守护进程循环模式
uv run evolver --loop

# 审查模式
uv run evolver --review

# 启动 WebUI 仪表盘（需 server extra）
uv run evolver webui

# 启动本地 A2A 代理
uv run evolver proxy
```

> WebUI 与本地代理需要 server extra：`uv sync --extra server`。核心进化引擎与 MCP server 无 fastapi 依赖。

**让宿主 Agent 加入蜂群（v1.98+ 的旗舰能力）**——引擎经 MCP stdio 接管宿主为进化执行器，一条命令体验完整闭环：

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py            # 确定性演示，不用 LLM
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py     # 全闭环演示
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm   # DeepSeek 真实执行
```

详见 [MCP 蜂群进化](#mcp-蜂群进化) 与 [examples/swarm-quickstart/](examples/swarm-quickstart/)。

### uvx（一次性 / 不装项目环境）

evolver 发布后（或想隔离工具环境、不跑 `uv sync`）：

```bash
# 从 PyPI（发布后）
uvx evolver --help
uvx evolver run

# 从本地检出（无需全局安装）
uvx --from . evolver run
uvx --from . evolver --loop
```

### 启动器选择

守护重生、生命周期 `start` 与 IDE hooks 经 `EVOLVER_LAUNCHER` 决定如何重新调起 evolver：

| 取值 | 行为 |
|---|---|
| `auto`（默认） | 有 `uv` + 项目根时优先 `uv run evolver`；否则 `uvx`；再否则 `python -m evolver` |
| `uv` | 强制 `uv run [--project <root>] evolver …` |
| `uvx` | 强制 `uvx [--from <root>] evolver …`（无 `uvx` 垫片时用 `uv tool run`） |
| `python` | 强制 `python -m evolver …` |

监管者可用 `EVOLVER_LOOP_COMMAND`（空格分隔）覆盖完整 argv。

## MCP 蜂群进化

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

**Claude Code**（项目根 `.mcp.json`）与 **Cursor**（`.cursor/mcp.json`）同构。现成配置在 [`examples/swarm-quickstart/mcp-host-configs/`](examples/swarm-quickstart/mcp-host-configs/)。

> 常用环境变量：`EVOLVER_SWARM_AUTO_HIJACK=1`（强制打开 HITL，并拒绝宿主转达放行；不改常驻 instructions）；`EVOLVER_HITL_MODE=on`（高危 solidify 需人类批准）；`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`（连续降级反馈自动暂停，默认 3）。

### 接管与闭环

- **注入**：本条消息已有别的任务就做那件事；没有时 `swarm_boot`，再用一句话说明实际状态。`boot_once` 只登记会话，不在开机时同步技能。冻结包或 Parent 基线缺失、或循环已暂停时不 tick（人可设 `EVOLVER_SWARM_GATE_HANDOFF=hotl` 跳过前两项，门照常拒绝发布）。说「停」「继续」由宿主转达 `swarm_supervise` pause / resume。首次准备（冻结包、另一上下文解 val、建基线）见 [examples/swarm-quickstart/README.md](examples/swarm-quickstart/README.md)。全文协议在 MCP prompt `evolver_swarm` 与 `swarm_boot` 的返回里
- **闭环协议**：`swarm_tick`（取 GEP 变异提示词）→ 宿主用自己的编辑工具执行变异 → `swarm_distill`（蒸馏 Gene/Capsule）→ `swarm_hypothesis`（一假说门：宿主声明本轮唯一假说，无假说则门拒）→ `swarm_solidify`（验证门 + 固化）→ `swarm_feedback`（统一评估信号 E，低分自动注入 repair-bias）→ 循环。`swarm_propose` 可从证据包发起干预提案，`swarm_report` 为心跳
- **安全双闸**：HITL 审批门（`evolver hitl list|approve|reject`，TTL 超时 fail-safe 拒绝）+ HOTL 监督（`evolver supervise status|pause|resume|direct|veto|unveto`，人在环上随时刹车/否决/转向）

### Hooks 集成（信号自动采集）

宿主支持文件 hooks 时安装钩子，session 边界与工具输出中的错误信号自动进入进化记忆：

```bash
uv run evolver setup-hooks --platform auto --project-dir /path/to/workspace
# 平台：cursor | claude-code | codex | kiro | opencode | vscode | generic | auto
```

MCP-only 宿主（无文件 hooks 能力）改用**进程内桥**：在会话开始/结束、以及观察到错误输出时调用 `swarm_hook_event`（`event=session_start|session_end|signal_detect`，`payload.content` 携带文本）；检测到的信号（`log_error` / `perf_bottleneck` / …）直接注入下一进化周期的基因选择。也可经 `swarm_hooks`（`action=status|install|uninstall`）由宿主自助安装文件钩子。

### MCP 资源与工具注解

除工具外，server 暴露四个只读资源（宿主可订阅/免工具往返读取）：

| URI | 内容 |
|---|---|
| `evolver://status` | 实时引擎/蜂群状态（JSON，含 HITL/HOTL/反馈摘要） |
| `evolver://instrument-prompt` | 当前渲染的接管提示词 |
| `evolver://dispatch/last` | 最近一次 GEP 变异提示词（`last_prompt.md`） |
| `evolver://events/recent` | 最近进化周期时间线（JSON） |

工具面共 26 个：8 个通用工具（`asset_search`、`asset_get`、`episode_get`、`mailbox_send`、`mailbox_poll`、`mailbox_ack`、`rebuild_views`、`cycle_timeline`）+ 18 个蜂群工具（`swarm_boot` / `tick` / `distill` / `hypothesis` / `propose` / `solidify` / `feedback` / `report` / `status` / `approvals` / `approval_resolve` / `supervise` / `hooks` / `hook_event` / `skills` / `workflow_run` / `workflow_act` / `workflow_status`）。

工具带 MCP 规范注解：`swarm_status`、`swarm_approvals`、`asset_search`、`episode_get`、`cycle_timeline` 等标记 `readOnlyHint`（宿主计划模式可安全跳过确认）；`swarm_solidify`、`swarm_hypothesis`、`swarm_propose`、`swarm_supervise`、`swarm_approval_resolve`、`swarm_workflow_act` 标记 `destructiveHint`（宿主可要求用户确认）。

### 技能生态桥（SKILL.md → 技能基因）

把宿主生态的技能文件接入进化引擎（EvoX SkillRegistry 模式：**project > user > builtin 三级优先、同名遮蔽**）。发现根目录：工作区 `.agents/skills` 与 `.claude/skills` > 用户 `~/.agents/skills`、`~/.zcode/skills`、`~/.claude/skills` > 引擎内置（可用 `EVOLVER_SKILL_ROOTS` 覆盖，顺序即优先级）。

```bash
uv run evolver skills scan              # 预览发现（含优先级与遮蔽）
uv run evolver skills sync --dry-run    # 预览将安装的技能基因
uv run evolver skills sync              # 转换并入 GEP 资产库（gene_distilled_s2g-*）
uv run evolver skills list              # 查看库中技能基因
```

同步后，技能以基因身份参与信号匹配与选择——例如一个「修复 ImportError」技能会在信号命中时被选入 GEP 提示词。宿主也可经 MCP `swarm_skills`（`scan|list|sync`）自助操作。

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

### 受控实验与消融裁决

消融基准检验既往周期记录是否真实促进宿主自修（对照 SelfSearch 协议，arXiv:2609.37968v2）。引擎提供离线/在线受控消融裁决套件：

```bash
# 对照有/无历史记录下的任务表现（真实 LLM 盲测）
uv run evolver experiment --ablation --tasks tasks.json \
    --from-episodes --placebo --model deepseek-flash --output result.json
```

核心科学防护：
- **占位对照臂（`--placebo`）**：为无记录臂注入等长中性上下文，隔离系统角色偏置，保证两臂差异仅在记录内容本身。
- **阶段出口契约（`--stage-exit`）**：机器强制的出口形态——真实 episode + placebo + 唯一任务 + 已知 commit + 落盘报告，五缺一即 exit 2，不产出报告。种子 AB/BA 交错取代固定臂序；逐调用记录（延迟、三段 tokens、错误类、served model）、逐题配对精确检验、采样冻结、服务端 prompt 失衡度量随报告一起落盘。
- **样本充足性审计**：自动对标 `MIN_N=30`；样本不足时裁决结论自动标明 `indicative only`，拒绝小样本误报。
- **依据透明分层**：严格区分成功率实质提升（`success_rate`）与纯 token 消耗平局裁决（`tokens_only`）。
- **全仓调用图钉**：单测扫描 `src/` 全仓，episode 写入口收敛于受检边界，杜绝任何自修改逻辑「自记自评」。

## 前置要求

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — 必需。Evolver 使用 git 进行回滚、爆炸半径计算和固化。在非 git 目录中运行将失败并显示明确错误信息。
- **[uv](https://docs.astral.sh/uv/)** — 推荐的包管理器。标准 `pip` / `python -m` 亦可使用。

## CLI 命令参考

| 命令 | 说明 |
|---|---|
| `run` | 运行单个进化周期（默认） |
| `--loop` / `--solo` / `--review` | 守护循环 / 完全离线模式（隐含 `--loop`） / 暂停待人审查 |
| `start` `stop` `restart` `status` `log` | 守护进程生命周期 |
| `check` `watch` | 健康检查与健康看守 |
| `solidify` | 应用待定变异（或提案） |
| `apply-proposal` | 机械应用基因提案 JSON（锚已验证、工作区安全） |
| `review` | 审查待固化项 |
| `report` | 周期裁决报告（负结果原样保留）+ 模式投影 |
| `gate-report` | 验收门 soak 报告：shadow 指标 + 转正判定 |
| `variants` | 变体档案：被拒但保留的候选（RSI P1-3） |
| `charter-check` | 机器回执：验证章程符合度与漂移 |
| `anchor init\|list\|run` | 仓外锚定套件：冻结验证契约（RSI P0-1） |
| `meta-report` | 改进机制遥测：RSI Table-8 面板 + 后代质量 |
| `gene-lifecycle list\|evaluate\|reinstate` | 基因生命周期治理（active / under_review / retired） |
| `soak setup\|exports\|status` | 运行态外置，不进 git 树 |
| `session start\|resume\|status\|round\|hypothesize\|reject\|accept\|incomplete\|extend\|finalize` | 配对进化会话（预算开局冻结 8；`extend` 仅人可调） |
| `self-report` | Autopoiesis 自检与规则演进 |
| `bench list\|init\|freeze\|gate\|baseline\|run\|prompt\|grade\|compare` | 任务包、Parent 基线、带 `--library` 的求解提示词、配对比较 |
| `library establish-parent` | 首写 Parent 库快照（solidify 调用不到） |
| `episode list\|show` | 周期记录——一次自改进过程的运行时记录 |
| `exec` `distill` `fetch` `reuse` `publish` `sync` `asset-log` `replay` `rebuild-views` | 执行桥、蒸馏 LLM 输出、Hub 获取/复用/发布、资产调用日志、SQLite 回放、派生视图 |
| `skill2recipe` | 将验证过的技能组合为可发布 GEP 配方 |
| `mcp` | 以 stdio 运行 MCP server（蜂群入口） |
| `hitl list\|approve\|reject` | HITL 审批门 |
| `supervise status\|pause\|resume\|direct\|veto\|unveto` | HOTL 监督 |
| `skills list\|scan\|sync` | 技能生态桥 |
| `workflow run\|templates\|status\|awaiting\|approve\|reject\|complete\|resume` | 持久化工作流引擎 |
| `experiment --ablation …` | 受控实验 / 消融裁决 |
| `webui` `login` `logout` `webui-token` `reset-local-secret` `setup-hooks` `trajectory` | 仪表盘、OAuth、令牌、IDE hooks、追踪转轨迹 |
| `atp` `atp-complete` `buy` `orders` `verify` | ATP 本地结算、auto-buyer 授权、下单 |
| `proxy` `proxy-token` | A2A 代理与本地 bearer 令牌 |
| `recipe list\|show\|apply\|cache-list\|cache-clear` | 配方中心 |

每个子命令都支持 `--help` 查看完整参数。

## 项目结构

```
src/evolver/
├── cli.py              # CLI 入口（argparse）、.env 加载、命令分发
├── config.py           # 运行时阈值 + 环境变量
├── canary.py           # Fork 金丝雀：验证 CLI 可正常加载
├── swarm.py            # 蜂群核心：接管提示词 + 闭环工具
│                       #   （tick/distill/hypothesis/propose/solidify/feedback/
│                       #    report/status/supervise/hooks/hook_event/skills），
│                       #   stdout 全捕获
├── mcp_server.py       # MCP stdio server：8 通用 + 18 蜂群工具、
│                       #   evolver_swarm prompt、evolver://* 资源、
│                       #   工具注解（mcp>=2.0 MCPServer）
├── evolve/
│   ├── runner.py       # 周期编排（单次 + 守护循环）
│   ├── guards.py       # 起飞前检查（负载、RSS、冷却）
│   ├── post_cycle.py   # 周期末钩子（ATP auto-buyer）
│   └── pipeline/       # 七阶段流水线 + preflight（异步函数）
│       ├── collect.py      # 日志扫描 + living_memory
│       ├── signals.py      # 信号 + guard/preflight/learning
│       ├── hub.py          # Hub 查询
│       ├── enrich.py       # 记忆建议 + memory_bridge 双向同步
│       ├── autopoiesis.py  # SelfReport + homeostasis
│       ├── select.py       # Gene/Capsule 选择 + 创新记录
│       └── dispatch.py     # GEP 提示词 + solidify 状态
├── gep/                # GEP（基因组进化协议）核心
│   ├── schemas/        # Pydantic 模型：Gene、Capsule、Task、Protocol
│   ├── asset_store.py  # JSON/JSONL 持久化与叠加语义
│   ├── cognition.py    # 高级认知编排（回忆/探索/课程/反思）
│   ├── solidify.py     # 应用基因 → 验证 → 持久化 → 发布
│   ├── selector.py     # 信号匹配 + 表观遗传偏置
│   ├── signals.py      # 信号收集与分类
│   ├── feedback.py     # 统一评估信号 E（EvoX 收割）
│   ├── hitl.py         # HITL 审批门（超时 fail-safe 拒绝）
│   ├── supervision.py  # HOTL 监督（pause/veto/directive + 绊线）
│   ├── skill_assets.py # SKILL.md 桥（project > user > builtin）
│   ├── episode_record.py   # 周期记录：一次自改进过程的运行时记录
│   ├── evolution_session.py# 配对会话机（§5.1）+ 一假说门
│   ├── library.py      # 内容寻址库快照（打分对象是快照）
│   ├── bench/          # 冻结任务包、评分、冻结门、配对检验
│   ├── validator/      # 沙箱执行器、报告器、质押引导
│   └── ...             # 100+ 模块
├── proxy/              # 本地 HTTP 代理（CLI 默认 127.0.0.1:8081；路由 /v1/a2a）
│   ├── server/routes.py    # FastAPI 路由（task/ATP/extensions）
│   ├── router/             # LLM 路由、特性开关、SSE 流式
│   ├── extensions/         # DM、会话、技能更新、追踪控制
│   ├── mailbox/store.py    # 本地邮箱 JSONL 存储
│   ├── sync/               # Hub 双向同步引擎
│   └── lifecycle/manager.py# 代理生命周期 + 心跳
├── atp/                # Agent 交易协议市场
│   ├── protocol.py         # 枚举与 Pydantic 模型
│   ├── auto_buyer.py       # 自动发现能力缺口（可选、有预算）
│   ├── auto_deliver.py     # 自动认领并交付任务
│   └── settlement.py       # 本地账本
├── adapters/           # IDE 集成钩子
│   ├── hook_adapter.py     # 共享适配器逻辑
│   ├── setup_hooks.py      # 为 Cursor、Claude Code、Codex、Kiro、OpenCode 安装钩子
│   └── scripts/            # 运行时脚本（session_start、signal_detect）
├── ops/                # 运维（生命周期、健康、自修复、soak 环境）
│   ├── lifecycle.py        # 跨平台守护进程管理
│   ├── health_check.py     # 磁盘/内存/进程检查
│   └── self_repair.py      # Git 紧急修复
├── bench/              # 工作区基准（健康任务 + fitness 账本）
├── experiment/         # 受控实验、真实 LLM 消融、占位对照臂与统计
├── recipe/             # 配方中心（list/show/apply + 缓存）
├── solo/               # 受限野外离线模式（硬切网络/ATP/验证者）
└── webui/              # FastAPI 只读仪表盘
    ├── app.py            # 仪表盘 + SSE `/events/stream`
    ├── dashboard.py      # 暗色 HTML 仪表盘（实时事件）
    ├── client/           # 内嵌 JS/CSS（SSE、bootstrap、i18n）
    └── observer/         # 数据聚合模块

tests/                  # 342 个测试文件，4,227 条用例（pytest；含 MCP 协议
                        #   E2E 与 tests/e2e/ 下的真 LLM 闭环 E2E）
scripts/                # 23 个 CLI 辅助脚本（见「脚本工具」）
src/evolver/assets/gep/ # 种子基因库
memory/                 # 运行时数据（graph JSONL、reviews JSONL）
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | 每用户运行时状态目录 |
| `EVOLVER_REPO_ROOT` | 自动检测 | 覆盖仓库根目录 |
| `OPENCLAW_WORKSPACE` | （无） | 工作区根覆盖 |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP 资产存储 |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 进化状态 |
| `EVOLVER_SESSION_SCOPE` | （无） | 按项目隔离的状态分段 |
| `EVOLVE_STRATEGY` | `balanced` | 进化策略预设 |
| `EVOLVE_BRIDGE` | auto | Git worktree 变异桥接 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | 回滚策略：stash / hard / none |
| `EVOLVER_MAX_CYCLES_PER_PROCESS` | `0`（不限） | 单守护进程最大周期数 |
| `EVOLVER_CYCLE_TIMEOUT_MS` | `2700000` | 单周期硬超时 |
| `EVOLVER_VALIDATOR_ENABLED` | 选择启用（`1`/`true` 开启） | 验证者守护 |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI 端口 |
| `EVOLVER_PROXY_PORT` | `8081` | 本地代理端口（`EVOMAP_PROXY_PORT` 别名）；可用 `evolver proxy --port` 覆盖 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | 自动生成 | 节点身份 |
| `GITHUB_TOKEN` | — | GitHub API 令牌 |
| `EVOLVER_HITL_MODE` | `off` | HITL 审批门——`on` 时高危 solidify 需人类批准（off 仍记审计；未知值 fail-closed 为 on） |
| `EVOLVER_HITL_TTL_MS` | `1800000` | HITL 待决请求 TTL——超时 fail-safe 拒绝 |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL 绊线——连续 N 次降级反馈自动暂停（`0` 关闭） |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | 蜂群反馈降级阈值——低于此分或 `success=false` 注入 repair-bias |
| `EVOLVER_ADAPTIVE_MUTATION` | `true` | 反馈驱动之变异类别权重自适应 |
| `EVOLVER_ADAPTIVE_MUTATION_SHIFT` | `0.2` | 自适应权重偏移幅度（归一化前） |
| `EVOLVER_SWARM_AUTO_HIJACK` | `false` | 置 `1` 时强制打开 HITL，并拒绝宿主转达放行。不改常驻 instructions |
| `EVOLVER_SWARM_GATE_HANDOFF` | `human` | 冻结包或基线缺失时：`human` 让 boot/tick 返回 `await_human`；`hotl` 照常 tick（门照常拒绝回滚，不发布） |
| `EVOLVER_SKILL_ROOTS` | 三级默认根 | 技能根目录覆盖（os.pathsep 分隔，顺序即优先级） |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | 验收门转正判定之最小 gated 样本数（false-kill 上限 0.1、拦截率区间 0.05–0.5 是代码常量） |
| `EVOLVER_ACCEPTANCE_SHADOW` | `true` | shadow 模式：只度量不执法；置 `0` 是人类决策 |
| `EVOLVER_FITNESS_GATE_ENFORCE` | 关闭 | 把 `no_improvement` 变异回滚，而不只是上报 |
| `EVOLVER_GENE_INERT_BAN_STREAK` | `8` | 惰性基因连续 N 轮零结果后禁选 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | 已应用基因冷却窗口——近期成功固化者选择打分惩罚 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY` | `0.25` | 冷却惩罚乘数（非禁选：唯一匹配仍可选） |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl 轮转阈值 |
| `EVOLVER_MEMORY_GRAPH_RETENTION_COUNT` | `7` | 轮转归档保留个数（`0`=全删） |
| `EVOLVER_MEMORY_GRAPH_AUTO_ROTATE` | `true` | 设 `false`/`0`/`no` 关闭自动轮转 |
| `EVOLVER_ROTATE_GZIP_MAX_MB` | `32` | 更大文件仅 rename 不压缩（防 OOM） |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 反滥用遥测模式（`heartbeat`/`off`） |
| `EVOLVER_OUTCOME_REPORT` | `off` | 向 Hub 上报复用结果以获归因 |
| `EVOLVER_REUSE_ATTRIBUTION` | `off` | 复用归因模式 |
| `EVOLVER_EVAL_WORKTREE_STRICT` | 关闭 | 评估 worktree 失败时：`1` 则失败而非回退 live cwd |
| `EVOLVER_AUTOPOIESIS` / `EVOLVER_AUTOPOIESIS_WRITE` | `1` / `1` | Autopoiesis 阶段 / 持久化规则与活记忆（`0`=dry-run） |
| `EVOLVER_LEARNING_SIGNALS` | `1` | 注入环境学习信号 |
| `EVOLVER_LAUNCHER` | `auto` | 重调起启动器：`auto` / `uv` / `uvx` / `python` |
| `EVOLVER_LOOP_COMMAND` | （无） | 守护循环命令的完整 argv 覆盖 |
| `EVOLVER_FF_*` | 见各开关 | 特性开关（`EVOLVER_FF_ENABLE_RECALL_INJECT`、`_REFLECTION`、`_EXPLORE`、`_CURRICULUM`、`_SKILL_AUTO_UPDATE` 等）——环境变量优先于磁盘开关存储 |

## 实现状态

> **总体评估**（2026-10-04）：包版本 **1.113.0**。配对会话门在 2026-09-27 收口，没有候选在密封 val 上优于 Parent。现行章程是 [演进方案.md](演进方案.md)：经验即证据。出口是一次有/无记录消融；n=3 的合成记录对照只是线索（indicative only）。验收门保持 shadow。下表百分比是 2026-09-05 的快照，不是工作清单。

| 子系统 | 状态 | 说明 |
|---|---|---|
| **GEP 数据层** | ~90% | 种子基因 11×sha256；solidify 直测 + 学习助手 |
| **GEP 高级认知** | ~80% | 回忆/反思/蒸馏；探索/课程由 feature flag 控制 |
| **进化流水线** | ~90% | 7 阶段 + Autopoiesis + 硬超时；已应用基因冷却（v1.111） |
| **MCP 蜂群** | ~97% | 接管闭环 + E 反馈 + HITL/HOTL + Hooks/技能桥 + 工作流工具；dogfood 至 round-78 |
| **工作流引擎** | ~90% | WAL 持久化步骤（script/foreach/if/agent/approval/gate）；YAML + 角色 + 模板（v1.110） |
| **验收门** | ~85% | shadow soak + gate-report 判定；执法开关留人类 |
| **Proxy 基础设施** | ~85% | 多供应商、令牌复用、路径 CLI 参数、端口 **8081** |
| **ATP 市场** | ~65% | 本地结算；Hub 商业 E2E 待补 |
| **IDE 适配器** | ~85% | 运行时 hooks + py_compile 守卫 + MCP 进程内桥 |
| **Ops / Solo** | ~85% | lifecycle、force-update、`--solo` |
| **WebUI** | ~70% | SSR 仪表盘 + GitHub observer |
| **验证者** | ~50% | 沙箱框架存在；生产级网络隔离待完善 |
| **文档/发布** | ~90% | CHANGELOG + 版本 **1.113.0**；多 OS CI（Windows 为 blocking ＋ 锚套件） |

现行计划见 [演进方案.md](演进方案.md) 与 [TODO.md](TODO.md)。wikiskill 对照版是档案。

## 示例

| 示例 | 说明 |
|---|---|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **蜂群进化全闭环**——MCP 接管、tick→执行→distill→solidify→feedback、HITL/HOTL 运维（`--llm` 由 DeepSeek 真实执行；`demo_closed_loop_flash.py` 跑全闭环） |
| [`examples/hello-world/`](examples/hello-world/) | 在隔离工作区运行单次进化周期 |
| [`examples/daemon-loop/`](examples/daemon-loop/) | 持续守护进程、生命周期管理、启停/状态/日志 |
| [`examples/proxy-basics/`](examples/proxy-basics/) | A2A 代理、代理令牌、curl API 示例、LLM 中继 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | 为 Cursor、Claude Code、OpenCode、Codex 安装会话钩子 |
| [`examples/solo-mode/`](examples/solo-mode/) | 完全隔离离线模式——无 Hub、无网络 |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 自检、经验教训、自生规则 |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 蒸馏 → 复用 → 发布资产全生命周期 |
| [`examples/skill2recipe/`](examples/skill2recipe/) | 将 Agent 技能组合为 GEP 配方 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 下单/交付/心跳演示（可 mock Hub） |

## 测试

```bash
# 运行全部测试
uv run pytest tests/ -q

# 蜂群全量 E2E（stdio MCP，全部工具/资源/prompt + HITL/HOTL 流）
uv run pytest tests/e2e/ -q

# 真 LLM 闭环 E2E——DeepSeek（deepseek-v4-flash）扮演宿主执行器：
# tick → LLM 执行 GEP dispatch 提示词 → distill → feedback → 第二次 tick。
# 需要环境里有 DEEPSEEK_API_KEY（否则跳过）。
DEEPSEEK_API_KEY=sk-... uv run pytest tests/e2e/ -m llm -q
# 可选：DEEPSEEK_BASE_URL（默认 https://api.deepseek.com）、
#       DEEPSEEK_MODEL（默认 deepseek-v4-flash）

# 运行并生成覆盖率报告
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# 排除慢速测试（CI 默认）
uv run pytest -m "not slow"

# 代码检查 + 格式检查 + 类型检查
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src

# 验证所有模块导入
python scripts/validate_modules.py
```

## 脚本工具

| 脚本 | 用途 |
|---|---|
| `scripts/a2a_export.py` | 将资产导出为 A2A JSON |
| `scripts/a2a_ingest.py` | 导入 A2A 资产 |
| `scripts/a2a_promote.py` | 候选基因晋升为正式基因 |
| `scripts/analyze_by_skill.py` | 按技能分析进化事件 |
| `scripts/baseline_snapshot.py` | 快照基线以供比较 |
| `scripts/build_binaries.py` | PyInstaller 独立可执行文件构建 |
| `scripts/check_changelog.py` | CHANGELOG 与版本号一致性检查 |
| `scripts/env_inventory.py` | 环境清单报告 |
| `scripts/extract_log.py` | 按时间/类型过滤 events.jsonl |
| `scripts/generate_history.py` | GEP 事件时间线（Markdown） |
| `scripts/gep_append_event.py` | 手动追加 GEP 事件 |
| `scripts/gep_personality_report.py` | 人格状态 HTML 报告 |
| `scripts/harness_governance_check.py` | 测试台治理审计 |
| `scripts/human_report.py` | 生成 Markdown 进化报告 |
| `scripts/recall_verify_report.py` | 回忆/记忆图谱覆盖率报告 |
| `scripts/recover_loop.py` | 守护循环恢复诊断 |
| `scripts/seed_merchants.py` | ATP 商家服务种子数据 |
| `scripts/self_ab_acceptance.py` | 自我 A/B 验收助手 |
| `scripts/soak_env.py` / `scripts/soak_sprint24.py` | soak 环境助手 |
| `scripts/suggest_version.py` | 语义化版本号建议 |
| `scripts/validate_modules.py` | 验证所有模块可导入 |
| `scripts/validate_suite.py` | 导入检查 + 快速 pytest 集成门禁 |

## 架构

### 进化流水线（七阶段）

**起飞前检查**（`guards.py`）→ 可选 abort 并落盘 SelfReport 快照。

| 阶段 | 模块 | 职责 |
|---|---|---|
| 1. Collect | `collect.py` | 会话日志、失败诊断、`living_memory` |
| 2. Signals | `signals.py` | 提取信号；guard / preflight / learning 键 |
| 3. Hub | `hub.py` | Hub 任务/资产；hub 质量门数据 |
| 4. Enrich | `enrich.py` | 记忆图谱建议、`bidirectional_memory_sync` |
| 5. Autopoiesis | `autopoiesis.py` | SelfReport、viability、homeostasis、repair bias |
| 6. Select | `select.py` | Gene/Capsule + 变异类别 |
| 7. Dispatch | `dispatch.py` | GEP 提示词（`recall` + `autopoiesis_context`）、固化状态 |

**周期末**（`post_cycle.py`）——ATP auto-buyer tick。**固化**（`evolver solidify`）经 `gep/solidify.py` 单独运行。

### 核心概念

- **Gene（基因）** — 可复用的突变策略（signals_match → execution_trace）
- **Capsule（胶囊）** — 带有结果的具体执行实例
- **Epigenetics（表观遗传）** — 环境感知的基因抑制/激活
- **Solidify（固化）** — 将经验验证的突变应用到代码库
- **Episode record（周期记录）** — 一次自改进过程的运行时记录；消融裁决所依据的证据源
- **ATP** — Agent 交易协议，用于自主服务市场

## 与 Node.js 参考实现的差异

- **许可证**：Python 移植版使用 **Apache-2.0** 许可证分发（依据公开 API、测试契约与协议规范进行的独立净室行为等价实现）；Node.js 参考实现使用 GPL-3.0-or-later。
- **源码可见性**：Python 移植版完全可读且有完整文档；Node.js 核心文件经混淆保护。
- **数据库**：Python 移植版增加了 `ops/sqlite_store.py` 用于 SQLite 持久化（增强）。
- **配方中心**：Python 移植版包含 `recipe/` 模块（新功能）。
- **WebUI 前端**：Python 移植版提供内嵌 JS 客户端（`webui/client/`）与 SSE；非独立 SPA 构建。
- **受控消融实验**：Python 移植版内建 `experiment/` 模块，提供具备占位对照与样本量充足性门槛的严谨消融裁决体系。

## 安全模型

Evolver 需要文件系统与网络访问，护栏分多层实施：

- **起飞前检查**：自动修复陈旧 `.git/index.lock` 与未决 rebase/merge；负载超 `EVOLVE_LOAD_MAX` 时跳过周期；连续修复失败触发降级模式或硬中止；用户锁（`~/.evolver/user.lock`，带 TTL）防止 IDE 会话期间变异；`chore(release)` 提交附近跳过进化
- **爆炸半径**：每个基因声明 `constraints.max_files`（通常 4–20）与 `forbidden_paths`；A2A 门限 `A2A_MAX_FILES=5`、`A2A_MAX_LINES=200`；`EVOLVER_ROLLBACK_MODE=stash` 先 stash 再应用、失败可回滚
- **内容完整性**：资产 `asset_id` 内含 `sha256:` 内容哈希，加载时静默跳过哈希不符条目；`sanitize.py` 净化 Hub 资产危险字段
- **网络安全**：Proxy 默认只听 `127.0.0.1`；Hub 通信全走节点密钥签名 + 反滥用遥测；`webui-token` 签发 JWT，WebSocket 命令需管理员角色
- **用户密钥**：`redact.py` 从交互日志剥离 bearer token / API key / JWT / 密码；`.env` 与凭据永不入库；会话转录进 WebUI 前先打码
- **蜂群安全（HITL + HOTL）**：HITL 按决策阻塞（高危 solidify 过 `gep/hitl.py`，TTL 超时 fail-safe 拒绝，按 subject 幂等）；HOTL 监督叠加（pause/resume、veto 否决、directive 转向、降级连击自动暂停）；一切监督/审批动作入审计日志

## 反例（行不通的做法）

| 不要 | 为什么 |
|---|---|
| 在非 git 目录（如 `/tmp`）跑 evolver | 基因依赖 git 做爆炸半径追踪与回滚 |
| 把 `OPENCLAW_WORKSPACE` 指向生产服务器 | Evolver 会施加代码变异——请用隔离工作区 |
| 无 Hub 连接也无种子基因就开 `--loop` | 基因池会枯竭；调高 `EVOLVER_GENE_INERT_BAN_STREAK` |
| 同一工作区跑多个 evolver 实例 | 实例锁会阻止；按项目隔离用 `EVOLVER_SESSION_SCOPE` |
| 期待 `--solo` 立刻见效 | Solo 无 Hub 资产；基因池要多周期积累 |
| 在 CI/CD 里用 `--review` | 审查模式阻塞等 stdin；自动化请用 `--loop` |
| 同一仓库混跑 Node.js 与 Python evolver | 状态文件格式不同；请整体迁移到一个实现 |
| 刚设 `EVOLVER_AUTOPOIESIS_WRITE=1` 就去看 `LESSONS_LEARNED.md` | 经验教训在周期结束后异步写入 |
| 在写候选的同一上下文里给候选打分 | 配对会话与 bench 规则要求 val 求解在独立上下文进行 |

## Hub 连接

Hub（`A2A_HUB_URL`，默认 `https://evomap.ai`）提供资产发现（`GET /api/assets` 或 `evolver fetch`）、任务市场（`evolver sync` 或代理端点）、ATP 结算、SSE + 轮询双向事件同步。连接完全可选——`--solo` 关闭全部 Hub 功能；代理管理连接生命周期（启动 hello 心跳、不可达指数退避 1s→30s、反滥用遥测、`A2A_NODE_SECRET_VERSION` 密钥轮换）：

```bash
A2A_HUB_URL=https://your-hub.example.com uv run evolver proxy
```

## 文档

- [English README](README.md)
- [演进方案.md](演进方案.md) — 现行章程
- [TODO.md](TODO.md) — 该章程的工作清单
- [CHANGELOG.md](CHANGELOG.md) — 按 round 记账（当前 1.113.0）
- [AGENTS.md](AGENTS.md) — Agent 集成指南、编码规范、常见陷阱
- [DEBUG.md](DEBUG.md) — 排障手册：dogfood 与互锁 bug 的根因与可迁移经验
- [RSI演进对照.md](RSI演进对照.md) — 论文对照与 effective-L5 记录（档案）
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — 2026-09-01 审计（档案）
- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献指南
- [SKILL.md](SKILL.md) — Skill 使用参考
- [docs/env-registry.md](docs/env-registry.md) — 环境变量登记表

## 许可证

本软件遵循 [Apache License 2.0](LICENSE) 开源协议。

> **关于上游谱系的说明**：本项目是一个独立的 Python 净室行为等价重实现工程，基于公开协议与测试契约开发。原始 Node.js 参考实现由 EvoMap 组织以 GPL-3.0-or-later 许可分发。本项目保持 Apache-2.0 独立开源发布。
