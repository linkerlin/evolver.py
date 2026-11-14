# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · **简体中文** · [日本語](README.ja-JP.md) · [한국어](README.ko-KR.md)

**面向 AI 智能体的基因组自进化引擎（GEP-Powered Self-Evolution Engine）。**

---

## 📖 概述：迈向具有复利效应的智能体演进

在大语言模型（LLM）驱动的软件工程实践中，传统智能体往往受制于 **“单次推理无记忆、策略模式难沉淀、演化缺乏严谨判据”** 的困局。现存的开发助手虽能生成代码，却无法在长期的项目实践中自发提取成功经验、修复反复出现的工程摩擦，更无法在无人工介入时持续优化自身的策略集。

**`evolver.py` 为破除这一瓶颈而生。**

本项目是一个基于 **GEP（Genome Evolution Protocol，基因组进化协议）** 的智能体自进化系统。它构建了一个闭环的自演进回路：从代码仓库与运行时日志中捕获信号，匹配并派发变异策略，驱动外部宿主进行代码修改，并经过严密的验证门禁与科学消融实验，将有效的工程经验固化为可复用的“基因（Gene）”与“胶囊（Capsule）”。

### 核心设计哲学

1. **引擎不自建调度，宿主 Agent 即执行器**  
   `evolver.py` 本身不内置繁杂的私有 LLM 调度器，而是通过标准的 **MCP (Model Context Protocol) stdio** 协议将宿主智能体（如 Cursor、Claude Code、Codex、ZCode 等）直接接管为“进化执行器”。宿主原有的工具调用能力与工作区上下文成为了演化的手术刀，引擎则专注于信号捕获、策略决策与安全仲裁。

2. **经验即证据与递归套具工程（Experience as Evidence & Recursive Harness Engineering）**  
   对照前沿学术协议（*arXiv:2609.37968v2, SelfSearch*；*arXiv:2610.14224v1, Harness2*），系统将智能体在真实场景中的“一次自改进过程记录（Episode Record）”升格为一等经验源，并辅以机械式四向组件归因、跨轮行为对比增量与多提案选择性合成。拒绝黑盒的盲目变异与无校准的 LLM 自打分，每一次策略的入库与晋升都必须经受预演完整性门、受控对照消融裁决与样本量充足性检验（已在 30 条真实 MCP 结算与 32 题配对冻结包上通过双独立种子 `--stage-exit` 出口裁决：`p = 1.86e-09` / `2.98e-08`）。

3. **现代净室 Python 架构**  
   本项目是基于公开协议规范与测试契约、对 `@evomap/evolver` 机制进行的完全独立、行为等价的 Python 净室实现。代码基于现代技术栈（Python 3.12+、`asyncio`、`uv`、`Pydantic v2`、`httpx`、`FastAPI`）构建，结构清晰透明，采用宽松友好的 **Apache-2.0** 许可证分发。

---

## 🏛️ 系统架构与核心机制

`evolver.py` 的内部运转依托于严密的演进回路、分层数据模型与人机协同防护体系。

```
┌────────────────────────────────────────────────────────────────────────┐
│                        evolver.py 演化生命周期回路                     │
└────────────────────────────────────────────────────────────────────────┘

  [ 运行时环境 / 仓库日志 / 测试失败 ]
                   │
                   ▼
       ┌───────────────────────┐
       │   1. Collect (收集)   │ ── 扫描错误模式与活记忆 (Living Memory)
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │   2. Signals (信号)   │ ── 提取结构化信号 (环境/依赖/性能/错误)
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │   3. Hub (云端同步)   │ ── 检索远端生态中的候选变异与先验资产
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │   4. Enrich (认知丰富)│ ── 关联记忆图谱，注入既往干预与历史教训
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │5. Autopoiesis (自生)  │ ── 自检系统生命力，摩擦自动编码为免疫规则
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │   6. Select (选择)    │ ── 表观遗传匹配，挑选最具潜力的变异基因
       └───────────┬───────────┘
                   ▼
       ┌───────────────────────┐
       │  7. Dispatch (派发)   │ ── 组装含证据的变异提示词 (GEP Prompt)
       └───────────┬───────────┘
                   │
                   ▼  (经 MCP stdio 通道)
       ┌───────────────────────┐
       │ 宿主 Agent (执行器)   │ ── Cursor / Claude Code 执行工作区代码修改
       └───────────┬───────────┘
                   │
                   ▼
       ┌───────────────────────┐
       │  一假说门 & 固化验证   │ ── 声明唯一演化假说 ➔ 运行沙箱与测试集门禁
       └───────────┬───────────┘
                   │
     [ 晋升 / 草稿保留 / soft-accept（仅环境缺口） ]
                   │
                   ▼
       ┌───────────────────────┐
       │  Solidify (固化沉淀)  │ ── 经验写入 ~/.evolver/…
       └───────────────────────┘     （不自动 git commit）
```

### 1. 七阶段演进流水线（Evolution Pipeline）

每一次演化周期（Cycle）均由七个解耦的异步阶段构成：
- **Collect**：扫描本地日志、回溯失败诊断，读取 `LESSONS_LEARNED.md` 活记忆。
- **Signals**：从原始数据中提取分类信号（如 `log_error`、`perf_bottleneck`、环境依赖漂移等），结合问题价值与 WFQ 防饥饿队列排序，并按闲时调度器强度（`signal_only` / `standard` / `deep`）调节探索配额。
- **Hub**：向中心化或对等网络检索匹配的先验基因与协作任务。
- **Enrich**：双向同步记忆图谱，聚合失败侧证据与反思建议。
- **Autopoiesis（自生自愈）**：系统体内平衡维护，自动将多次发生的工程摩擦转化为规约规则。
- **Select**：基于变异偏置（Repair Bias）与探索度（Novelty）挑选适任策略；若前序 episode 归因为 `hurt`，自动冷却肇事基因并转向修复策略。
- **Dispatch**：生成结构化变异提示词并写入分发输出，唤醒宿主执行。

### 2. GEP 核心资产模型

- **Gene（基因）**：可复用的抽象变异策略，定义了“在何种信号模式下（signals_match）实施何种代码与行为干预（execution_trace）”。
- **Capsule（胶囊）**：包含输入、输出与环境结果的具体变异执行实例，记录真实的成功或失败轨迹。
- **Epigenetics（表观遗传调控）**：根据近期环境反馈动态抑制或激活特定基因，避免智能体陷入局部震荡。
- **Gene Lifecycle（生命周期治理）**：基因具备 `active`（活跃）、`under_review`（受审）、`retired`（退役）状态流转机制，零后效与负效基因自动被降权或移出候选池。

### 3. 双闸安全防御体系（HITL + HOTL）

代码自修改系统必须拥有牢不可破的安全边界。`evolver.py` 实现了双轨立体安全机制：
- **HITL（Human-In-The-Loop，人在环中审批门）**：对于跳过静态检查、大范围代码变异等高危动作（`solidify`），系统会阻塞执行并向操作者发起审批请求。支持全局审计与超时自动拒绝（Fail-Safe）。
- **HOTL（Human-On-The-Loop，人在环上动态监督）**：监控全局演化健康度。支持随时暂停/恢复（`pause`/`resume`）、模式否决（`veto`）以及下达方向信号（`directive`）。当系统连续遭遇降级反馈时，内置熔断绊线将自动暂停演进循环。

---

## ⚡ 核心能力全景

### 🐝 蜂群接管（MCP Swarm Evolution）
通过标准 MCP stdio 接口，宿主编辑器不仅是开发者的交互界面，更能作为执行引擎深度融入演化回路。引擎负责制定决策与验证规则，宿主负责精准变异。宿主支持工具注解（`readOnlyHint` 与 `destructiveHint`），在保证透明度的前提下实现无人值守平稳运行。

### 🌉 技能生态桥（Skill Ecosystem Bridge）
无缝收割现有智能体生态能力。系统自动扫描 `SKILL.md` 规范的技能资产，按照 **工作区（Project）> 用户级（User）> 引擎内置（Builtin）** 三级优先级进行覆盖与发现，并自动将技能蒸馏转换为系统内的 GEP 基因，使外部技能直接参与信号匹配与变异决策。

### 📋 协作即数据：持久化工作流引擎（Workflow Engine）
将复杂的工程任务定义为可版本化、可演化的 YAML 声明式工作流。支持 `agent` 认领步骤、`gate` 自动化级联检测（ruff ➔ mypy ➔ pytest）以及 `approval` 人工审批门。全流程依托预写日志（WAL）与状态快照，天然支持断点容灾续跑。

### 🔬 科学受控实验与消融裁决（Controlled Ablation Suite）
引入严格的科学评测框架，杜绝“自写自测、虚标成效”的伪自进化：
- **中性占位对照（Placebo Context）**：注入等长中性上下文，隔离系统角色偏置。
- **阶段出口契约（Stage Exit）**：强校验真实 episode、占位对照、已知 commit 与落盘报告，对标样本量阈值（`MIN_N=30`），样本不足时强制标记为 `indicative only`。
- **全仓调用图钉**：静态白名单扫描隔离写入边界，杜绝演进代码自我篡改评分结果。

### 🧩 递归套具工程与选择性合成（Recursive Harness Engineering — Harness2）
融汇 *Harness2*（*arXiv:2610.14224v1*）之机械式归因与对比合成思想，在不引入在线 LLM 裁判的前提下强化演化信噪比：
- **四向组件归因（`H2-1`）与跨轮行为对比增量（`H2-5`）**：引擎在周期结算时自动计算 `helped | hurt | no_observed_effect | confounded` 四向归因及 `newly_passed` / `regressed` / `persistent_failures` 跨轮检查跳变，向派发提示词注入 `[attribution]` 与 `[contrast]` 摘要，并机械阻断 `confounded`（多组件混杂变更）轮次污染持久基因库。
- **可迁移经验三元组与工作区事实隔离（`H2-2`）**：持久基因强制校验 `cue + lesson + evidence` 三元组（`--strict-transferable`），而将含路径、行号或 `in this workspace:` 前缀的本仓战术事实隔离于会话期 `WORKING_SESSION.md`（会话终结自动归档并清除）。
- **`INV × DOM` 正交作用域与选择性合成器（`H2-3`）**：正交划分不变量/验证面（`INV`）与领域实现（`DOM`）提案，在 `swarm_propose`、`solidify` 与 `evolver apply-proposal` 中机械合并互不冲突的 `helped` 变更或安全回退 `KEEP_BASE`，并在 `evolver variants` 中标识单组件可打捞语义变体（`~`）。
- **组件成本层级预演门（`H2-4`）与双层递归溯源（`H2-6`）**：执行 `Skill > Script > Subagent > Hook > Always-On Text` 静态契约门（`validate_harness_component_integrity`）与六维交付物合规核验，支持 $\mathcal{H}_0 + \mathcal{R}_t$ 成对库快照求解及 `evolver meta-report` 中的 `library_provenance`（`direct_copy / adapted / novel`）溯源面板。

---

## 🚀 快速上手

### 环境准备

确保系统已安装：
- **Python >= 3.12**
- **[Git](https://git-scm.com/)**（必须，系统利用 Git 实现爆炸半径管控与原子级回滚）
- **[uv](https://docs.astral.sh/uv/)**（强烈推荐的现代 Python 工具链）

```bash
# 克隆仓库并安装依赖
git clone https://github.com/linkerlin/evolver.py.git
cd evolver.py
uv sync
```

### 零干预三动词自动驾驶（`init` / `up` / `status`）

在任意 Python 项目根目录，仅靠三个零黑话动词即可完成开箱接入、自动驾驶守护与纯人话观测：

```bash
# 1. 一键零污染开箱（< 3s 返回）：
#    自动探测已安装宿主（Claude Code / Cursor / Codex / OpenCode / ZCode），
#    幂等写入 MCP 与会话钩子，本地配置记入 .git/info/exclude（git status 零脏文件），
#    并在剥离密钥的后台干净子进程中无感完成原生基线与仓外 Anchor 首写。
uv run evolver init

# 2. 纯人话状态灯面板（就绪灯、已晋升修复、节省验证秒数、金库算子、工作台草稿——零内部旗标）
uv run evolver status

# 3. 启动零干预自动驾驶守护（含自适应滑动会话与连续 3 轮空转休眠；--once 仅跑一轮）
uv run evolver up
```

进阶与专家子命令仍可直接调用或通过 `evolver internal <subcmd>` 访问：

```bash
uv run evolver run         # 运行单次演化周期
uv run evolver --loop      # 启动标准守护循环
uv run evolver --review    # 审查模式（变异后暂停等待人工审核）
uv run evolver check       # 系统健康检查
```

### 开箱诊断（`setup` / `doctor`）

即使冻结包或 Parent 基线尚未齐备，循环亦可正常启动（首次环境缺口仅作为软警告）。您随时可运行只读诊断或安全补齐命令：

```bash
uv run evolver doctor          # git、冻结包、Parent 基线、user lock
uv run evolver doctor --fix    # 写入冻结包；仅当 val 沙箱已经齐备时才测量基线
uv run evolver setup           # 等同 `doctor --fix`
```

退出码 `0` 表示可以继续（`soft_continue`），只缺包或基线也算。退出码 `2` 是硬阻塞（目录不是 git 仓库，或 user lock 被占用）。`loop_ready` 保持诚实：只有 git、冻结包、Parent 基线都在时才为真。`--fix` 不会编造 val 答案，也不会在候选对话里打开密封材料。

运行态一律置于源码树之外：`~/.evolver/workspaces/<id>/`（`<id>` 为 `sha256(realpath(repo))[:16]`，统一由 WAL 模式 `index.sqlite` 维护读索引）；低频运行开关统一收归 `~/.evolver/config.json`（或 `EVOLVER_CONFIG`）。若仓库里还留着遗留 `memory/`、`.evolver/gep/`：

```bash
uv run evolver migrate-state
```

`evolve_status` 会返回 `state_root`、`workspace_id`、`saved_validation_seconds` 及 `state_health.legacy_in_repo`（含 `migrate_command`）。

> **可选服务组件**：若需启动可视化 WebUI 仪表盘或分布式 A2A 代理，需安装 `server` 扩展依赖：
> ```bash
> uv sync --extra server
> uv run evolver webui   # 访问 http://127.0.0.1:8080 仪表盘
> uv run evolver proxy   # 启动本地 A2A 代理（默认端口 8081）
> ```

---

## 🛠️ 接入宿主智能体（MCP 配置）

在目标项目内执行 `uv run evolver init` 即可全自动写入 MCP 配置与会话钩子，免去手改 JSON。如需手动配置，亦可参考下方示例。

### 1. 配置宿主 MCP 客户端

以 **Cursor**（`.cursor/mcp.json`）与 **Claude Code**（`.mcp.json`）为例：

```json
{
  "mcpServers": {
    "evolver": {
      "command": "uv",
      "args": ["--project", "/绝对路径/to/evolver.py", "run", "evolver", "mcp"]
    }
  }
}
```

以 **ZCode** 或直接指定虚拟环境 Python 为例：

```json
{
  "mcpServers": {
    "evolver": {
      "command": "/绝对路径/to/evolver.py/.venv/bin/python",
      "args": ["-m", "evolver.mcp_server"]
    }
  }
}
```

`uv sync`、拉取更新或升级之后，请**重启 MCP 进程**以重新加载新模块（可通过 `evolve_status.source_revision` 核对当前源码 git SHA）。在 Grok Bot 上，请将 `EVOLVER_REPO_ROOT` 指向 `/workspace/evolver-research/evolver.py`（详见 [`examples/swarm-quickstart/README.md`](examples/swarm-quickstart/README.md)）。

### 2. FSM 动态门控三工具宿主协议

`evolver.py` 基于 `notifications/tools/list_changed` 提供零认知负担的**有限状态机（FSM）三工具原子 MCP 目录**，彻底消除多步手工串联仪式与复杂布尔旗标：

- **`IDLE` 态**（无在途周期——仅暴露核心动作 `evolve_begin` 与只读 `evolve_status`；`run_lens` 与 `evolve_settle` 物理隐藏）：
  1. `evolve_status`：只读查询 FSM 状态、金库算子数、当前信号与累计节省验证秒数（`saved_validation_seconds`）。
  2. `evolve_begin`：
     - **不传假说**（`hypothesis=""`）：执行零副作用信号与推荐算子预览（`discovery_only=true`），状态保持 `IDLE`。
     - **传入一句可证伪假说**（`hypothesis="..."` 及可选 `target_files`）：前置锁定本轮唯一演化假说，对未初始化工作区自动静默触发后台自举，按效用密度（`utility / token_cost`）装配 `< 4,000 tokens` 高信噪比 GEP 提示词，启动周期黑匣子，并推送 `notifications/tools/list_changed` 切入 `ACTIVE_RUN`。
- **`ACTIVE_RUN` 态**（物理隐藏 `evolve_begin` 杜绝重复开局；解锁暴露 `run_lens` + `evolve_settle` + `evolve_status`）：
  3. `run_lens`*（只读）*：运行确定性 Python AST 与依赖诊断透镜（`ast_hotspot`、`import_impact`、`trace_locator`、`contract_surface`），输出自动经 `val_seal` 脱敏。
  4. *（宿主使用原生编辑工具修改工作区代码）*
  5. `evolve_settle`：默认运行 **`< 3s` L0 AST 反向依赖闪电验证**（通过 `gep/import_graph.py` 仅跑改动文件 `ruff` 与反向导入闭包关联 `pytest`，高危面自动升级 L2），在周期边界收束**带内黑匣子（`blackbox`）**（采集前后 AST 增量、透镜调用栈、diff 统计与墙钟耗时——无需本地 HTTP 代理即达 100% 引擎自记覆盖），落盘不可变 `episode_record`、同步 `index.sqlite` 读索引，并自动推通知切回 `IDLE`。

只读辅助工具（`episode_get`、按问题与行号窗口放大截断输出的 `episode_inspect`、`tool_asset_search`、`tool_asset_get`、`tool_cycle_timeline`）在两态下常驻可用。正向晋升入库后，后台隔离 `eval_worktree` 会异步执行 **L1 守护门**（子包 `mypy` 与关联回归集），一旦发现跨模块回归即自动将该算子降级为 `under_review`。

#### 双轨结算契约：工作台保草稿 × 金库严晋升（v1.114.0）

- **金库晋升（`ok=true, outcome="promoted"`）**：验证全绿且净增益时，经验与资产写入 `~/.evolver/workspaces/<id>/`，绝不自动执行 `git commit`。
- **工作台草稿保留（`ok=false, outcome="draft_preserved"`）**：任何检查失败（`pytest` / `ruff` / `mypy`）或适应度未胜（`drop`、`flat`、`regression`）一律诚实返回 `ok=false`——工作区补丁**原位保留不丢失**（同时快照备份至 `rejected_stashes/<run_id>/`），返回精确到出错 `file:line` 的恒 3 行 `actionable_fix`，**正向基因金库严格 `+0`**。宿主按 3 行指引修好后即可重开下一轮。
- **首轮环境缺口（`no_baseline`、`pack_absent`、`unmeasured`）**：附带明确 `warning` 软放行（`soft_continue`），绝不伪造 Parent 基线、亦不打开 `val` 密封材料。
- **安全硬阻断回滚**：diff 中含密钥或凭据、改写 `~/.evolver/` 受保护状态或触发 `val_seal` 泄露时，立即硬拒绝并回滚。

### 3. 一键体验闭环脚本

无需繁琐配置，运行随附的演示脚本直观感受演进流程：

```bash
# 1. 运行确定性闭环演示（无需真实 LLM API Key）
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 2. 运行完整闭环演示
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py

# 3. 连接 DeepSeek 真实执行宿主变异
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

---

## 🧭 CLI 指令全景

系统提供了按职责划分的高清晰度命令行接口：

| 领域分类 | 核心命令 | 功能说明 |
|---|---|---|
| **零干预主表面**| `evolver init` | `< 3s` 零污染一键开箱：探测本机 IDE、幂等注入 MCP 与 Hooks、写入 `.git/info/exclude` 并后台干净子进程自举基线与 Anchor |
| | `evolver up` / `auto` | 启动零干预自动驾驶守护（支持 `--once` 单轮；内置自适应滑动会话与连续 3 轮空转休眠） |
| | `evolver status` | 纯人话状态面板（就绪灯、已晋升修复、节省验证秒数、金库算子、工作台草稿；`--json` 供机器读取） |
| **演化控制** | `evolver run` | 触发单个自演化周期（默认动作） |
| | `evolver --loop` | 启动自主演进守护进程 |
| | `evolver --review` | 交互式审查模式，变异后等待操作者确认 |
| | `evolver solidify` | 验证（`--validation-scope=related\|cascade`）并结算待定轮。适应度未胜与验证失败按 `draft_preserved` 结算（`ok=false`；补丁原位保留附 3 行 `actionable_fix`，备份在 `rejected_stashes/`）。首轮环境缺口 soft-accept。不自动 git commit；硬阻断仍回滚。`--restore-stash` 恢复备份 stash |
| | `evolver setup` | 开箱入口，等同 `doctor --fix` |
| | `evolver doctor` | 诊断 git / 冻结包 / Parent 基线 / user lock（`--fix` 安装冻结包；仅当 val 沙箱已齐时测量基线） |
| | `evolver round --host` | 宿主单入口协议命令，一步串起 `boot → status → tick → checklist` |
| | `evolver migrate-state` | 将仓库内遗留 `memory/` 与 `.evolver/gep/` 一键迁入外置状态根 `~/.evolver/workspaces/<id>/` |
| | `evolver apply-proposal` | 应用单份结构化基因提案，或对多份 `INV × DOM` 提案执行机械式选择性合成 |
| | `evolver session` | 开启或管理受控配对演进会话（支持假说记录） |
| **蜂群与监督**| `evolver mcp` | 启动基于 stdio 的 MCP 服务端（宿主接管入口） |
| | `evolver hitl` | 人在环中审批管理（`list` / `approve` / `reject`） |
| | `evolver supervise` | 人在环上动态监督（`status` / `pause` / `resume` / `veto`） |
| | `evolver setup-hooks` | 为当前工作区配置 Cursor / Claude Code 等 IDE 自动钩子 |
| | `evolver charter-check` | 核验运行态环境与现行章程符合性回执 |
| **资产与知识**| `evolver skills` | 扫描、预览并同步外部 `SKILL.md` 到 GEP 资产库 |
| | `evolver distill` | 从 LLM 响应蒸馏 Gene / Capsule（支持 `--strict-transferable` 三元组门禁） |
| | `evolver gene-lifecycle`| 查看与维护基因状态（`active` / `under_review` / `retired`） |
| | `evolver variants` | 查看拒绝但保留的变体档案（`*` 可重派发、`~` 单组件语义可打捞） |
| | `evolver library` | 管理内容寻址库快照（`establish-parent` 首写 / `publish` 晋升） |
| | `evolver episode` | 检索历次自改进记录（Episode Record），或用 `episode inspect` 按问题读回截断原文 |
| | `evolver self-report` | 触发 Autopoiesis 系统自检，更新活记忆与自生免疫规条 |
| **实验与评测**| `evolver experiment` | 运行严谨的受控消融实验（`--ablation`、`--placebo`、`--stage-exit`） |
| | `evolver bench` | 执行冻结基准测试任务包、基线对比与配对库快照求解 |
| | `evolver anchor` | 初始化与运行仓外冻结锚定契约评测 |
| | `evolver gate-report` | 输出验收门（Shadow Gate）的浸泡观察与转正评估报告 |
| | `evolver meta-report` | 输出 Table-8 六维面板、后代变异质量与 `library_provenance` 库溯源报告 |
| **运维与服务**| `evolver check` / `watch` | 系统健康诊断与持续状态巡检 |
| | `evolver start` / `stop` | 跨平台系统级守护进程生命周期控制 |
| | `evolver webui` | 启动本地只读数据可视化看板（需 `server` 扩展） |
| | `evolver proxy` | 启动本地 A2A 协议代理服务（需 `server` 扩展） |

---

## 🔒 安全模型与工程护栏

`evolver.py` 具有自动修改代码并提交的能力，因此安全设计贯穿于每一个执行环节：

- **Git 爆炸半径，双轨制（v1.114.0）**：基因仍限定文件上限（`constraints.max_files`）与禁区路径（`forbidden_paths`）。solidify 不自动提交。缺包或缺基线 soft-continue 且 soft-accept；分数持平或下降、以及普通验证失败，按 `draft_preserved` 结算——工作区保持宿主留下的样子（补丁原位保留，备份在 `rejected_stashes/<run_id>/`），经验只写入 `~/.evolver/workspaces/<id>/`。硬阻断仍回滚：diff 中的密钥、指向 `~/.evolver/` 的修改、`val_seal` 泄露。soft-accept 与草稿保留都不写入 Parent 基线、都不进正向金库。
- **内容寻址与哈希防篡改**：资产 ID 强制绑定 SHA-256 摘要（如 `sha256:...`），存储与加载过程实时比对，静默剔除篡改条目；输入经专门的净化器（`sanitize.py`）过滤危险属性。
- **敏感凭据脱敏防护**：系统集成专门的过滤引擎，在所有落地事件、提示词缓存与 WebUI 序列化前，严格擦除 API 密钥、JWT 令牌、密码及会话痕迹。
- **单实例与状态互斥锁**：通过 OS 级单实例锁（`instance_lock.py`）保障同一工作区永远只有一个演化循环在写入，根绝多进程并发带来的状态竞态与脏数据覆盖。

---

## 🗺️ 项目结构导航

```
src/evolver/
├── cli.py                  # CLI 入口定义、参数解析与全局分发
├── config.py               # 统一配置体系、阈值定义与环境变量映射
├── swarm.py                # 蜂群核心协议：接管提示词组装与执行闭环调度
├── mcp_server.py           # 标准 stdio MCP 协议实现（全套通用/蜂群工具与资源）
├── evolve/                 # 自演化编排体系
│   ├── runner.py           # 周期控制器与守护循环守护进程
│   ├── guards.py           # 起飞前系统负载、内存与健康护栏
│   └── pipeline/           # 解耦的七阶段演进流水线（Collect 至 Dispatch）
├── gep/                    # GEP（基因组进化协议）核心资产与策略库
│   ├── schemas/            # Pydantic 数据规范（Gene / Capsule / Task 等）
│   ├── lenses.py           # 只读 AST/反向依赖/异常栈/契约面诊断透镜（自动经 val_seal 脱敏）
│   ├── blackbox.py         # 周期边界带内黑匣子（前后 AST 增量、透镜调用栈、墙钟耗时）
│   ├── import_graph.py     # 标准库 AST 增量反向依赖图（驱动 < 3s L0 闪电验证漏斗）
│   ├── index_db.py         # WAL 模式 sqlite3 统一读索引（信号频次、算子命中率、归因与预算）
│   ├── episode_record.py   # 内容寻址 Episode Record、四向组件归因与跨轮对比增量
│   ├── working_memory.py   # 会话期 WORKING_SESSION.md 草稿与工作区事实隔离
│   ├── record_route.py     # 双向记录路线与 INV × DOM 正交作用域校验
│   ├── proposal.py         # 结构化基因提案与机械式选择性合成器
│   ├── policy_check.py     # 安全策略门、组件成本层级预演门与交付物六维合规核验
│   ├── variant_archive.py  # DGM 式拒绝变体档案与单组件语义打捞
│   ├── library.py          # 内容寻址库快照与成对求解提示词渲染
│   ├── asset_store.py      # 叠加式 JSON/JSONL 本地高性能存储
│   ├── hitl.py             # 人在环中（HITL）审批决策门
│   ├── supervision.py      # 人在环上（HOTL）实时监督与自动熔断
│   ├── skill_assets.py     # 外部技能生态桥接与蒸馏器
│   ├── gene_lifecycle.py   # 基因全生命周期流转与状态机治理
│   └── solidify.py         # 暂存、门禁、双轨结算（draft_preserved / 晋升）；写经验，不自动提交
├── bench/                  # 锚侧冻结任务包、评分器与统计检验套件
├── experiment/             # 受控消融裁决套件（双臂盲测、占位对照与充足性审计）
├── adapters/               # IDE 深度集成适配器（Cursor / Claude Code / Codex 等钩子）
├── proxy/                  # 本地 A2A 分布式代理与模型路由矩阵
└── webui/                  # 只读可视化仪表盘（嵌入式前端与 SSE 实时事件流）
```

---

## 📚 延伸阅读与开发指南

- **[循序渐进实战教程（tutorials/）](tutorials/README.md)**：不背术语、从零拆解 `evolver.py` 运作机制的五讲中文动手指南。
- **[演进方案.md](演进方案.md)**：现行最高章程（**零干预自进化：算子即基因，回放即裁决**），阐述系统从“经验即证据”（归档于 [`演进方案_经验即证据.md`](演进方案_经验即证据.md)）迈向零干预自动驾驶、可执行算子基因（EOG）与双源时间胶囊真实代码回放裁决的完整架构蓝图。
- **[TODO_VISTA.md](TODO_VISTA.md) 与 [TODO_HARNESS2.md](TODO_HARNESS2.md)**：零参数机械套具落地清单，涵盖 VISTA 现场重注视/压缩门以及 Harness2（`H2-1`..`H2-6`）四向归因、工作区事实隔离与选择性合成。
- **[AGENTS.md](AGENTS.md)**：面向 AI 智能体开发者的行为准则、避坑指南与架构细节。
- **[DEBUG.md](DEBUG.md)**：深度调试手册，记录互锁排查、复杂边缘条件与稳定性实践。
- **[CHANGELOG.md](CHANGELOG.md)**：详细的版本演进记录与发布说明。
- **[CONTRIBUTING.md](CONTRIBUTING.md)**：代码贡献与测试规范指南。

---

## 📄 开源许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证开源发布。

> **关于谱系传承之说明**：`evolver.py` 是依据公开标准、测试契约与行为协议独立研发的 Python 净室实现。原始参考概念源自 EvoMap 组织，本项目在保持架构纯净与现代化的同时，以更加宽松、对工程友好的 Apache-2.0 协议独立分发。
