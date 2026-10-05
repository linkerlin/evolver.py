# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · **简体中文** · [日本語](README.ja-JP.md) · [한국어](README.ko-KR.md)

**面向 AI 智能体的基因组自进化引擎（GEP-Powered Self-Evolution Engine）。**

---

## 📖 概述：迈向具有复利效应的智能体演进

在大语言模型（LLM）驱动的软件工程实践中，传统智能体往往受制于**“单次推理无记忆、策略模式难沉淀、演化缺乏严谨判据”**的困局。现存的开发助手虽能生成代码，却无法在长期的项目实践中自发提取成功经验、修复反复出现的工程摩擦，更无法在无人工介入时持续优化自身的策略集。

**`evolver.py` 为破除这一瓶颈而生。**

本项目是一个基于 **GEP（Genome Evolution Protocol，基因组进化协议）** 的智能体自进化系统。它构建了一个闭环的自演进回路：从代码仓库与运行时日志中捕获信号，匹配并派发变异策略，驱动外部宿主进行代码修改，并经过严密的验证门禁与科学消融实验，将有效的工程经验固化为可复用的“基因（Gene）”与“胶囊（Capsule）”。

### 核心设计哲学

1. **引擎不自建调度，宿主 Agent 即执行器**  
   `evolver.py` 本身不内置繁杂的私有 LLM 调度器，而是通过标准的 **MCP (Model Context Protocol) stdio** 协议将宿主智能体（如 Cursor、Claude Code、Codex、ZCode 等）直接接管为“进化执行器”。宿主原有的工具调用能力与工作区上下文成为了演化的手术刀，引擎则专注于信号捕获、策略决策与安全仲裁。

2. **经验即证据（Experience as Evidence）**  
   对照前沿学术协议（*arXiv:2609.37968v2, SelfSearch*），系统将智能体在真实场景中的“一次自改进过程记录（Episode Record）”升格为一等经验源。拒绝黑盒的盲目变异，每一次策略的入库与晋升都必须经受严格的对照消融裁决与样本量充足性检验。

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
          [ 通过门禁检验 ]
                   │
                   ▼
       ┌───────────────────────┐
       │  Solidify (固化沉淀)  │ ── Git 提交入库 ➔ 基因生命周期晋升 ➔ 反馈自适应
       └───────────────────────┘
```

### 1. 七阶段演进流水线（Evolution Pipeline）

每一次演化周期（Cycle）均由七个解耦的异步阶段构成：
- **Collect**：扫描本地日志、回溯失败诊断，读取 `LESSONS_LEARNED.md` 活记忆。
- **Signals**：从原始数据中提取分类信号（如 `log_error`、`perf_bottleneck`、环境依赖漂移等）。
- **Hub**：向中心化或对等网络检索匹配的先验基因与协作任务。
- **Enrich**：双向同步记忆图谱，聚合失败侧证据与反思建议。
- **Autopoiesis（自生自愈）**：系统体内平衡维护，自动将多次发生的工程摩擦转化为规约规则。
- **Select**：基于变异偏置（Repair Bias）与探索度（Novelty），挑选适任策略。
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

---

## 🚀 快速上手

### 环境准备

确保系统已安装：
- **Python >= 3.12**
- **[Git](https://git-scm.com/)**（必须，系统利用 Git 实现爆炸半径管控与原子级回滚）
- **[uv](https://docs.astral.sh/uv/)**（强烈推荐的现代 Python 工具链）

```bash
# 克隆仓库并安装依赖
git clone https://github.com/evomap/evolver.py.git
cd evolver.py
uv sync
```

### 基础运行体验

```bash
# 运行单次演化周期
uv run evolver run

# 启动持续守护进程循环
uv run evolver --loop

# 启动审查模式（变异后暂停等待人工审核）
uv run evolver --review

# 启动系统健康检查
uv run evolver check
```

> **可选服务组件**：若需启动可视化 WebUI 仪表盘或分布式 A2A 代理，需安装 `server` 扩展依赖：
> ```bash
> uv sync --extra server
> uv run evolver webui   # 访问 http://127.0.0.1:8080 仪表盘
> uv run evolver proxy   # 启动本地 A2A 代理（默认端口 8081）
> ```

---

## 🛠️ 接入宿主智能体（MCP 配置）

将 `evolver.py` 作为 MCP Server 接入您的日常 IDE 与编码智能体中，让它们成为演化的执行单元。

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
      "args": ["-m", "evolver.mcp_server"],
      "env": {
        "EVOLVER_SWARM_AUTO_HIJACK": "0"
      }
    }
  }
}
```

### 2. 闭环工具协议调用链

接入后，宿主智能体即可通过以下标准工具链协作运转：
1. `swarm_boot`：初始化演化会话，报告当前状态。
2. `swarm_tick`：获取最新的 GEP 变异提示词及上下文。
3. *（宿主执行文件修改与逻辑重构）*
4. `swarm_distill`：从修改成果中提取出结构化 Gene 与 Capsule。
5. `swarm_hypothesis`：在验证前向系统提交本轮演化的唯一假说声明。
6. `swarm_solidify`：触发沙箱门禁检验，验证通过后执行 Git 固化提交。
7. `swarm_feedback`：回传多维评测指标，驱动下一轮自适应变异。

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
| **演化控制** | `evolver run` | 触发单个自演化周期（默认动作） |
| | `evolver --loop` | 启动自主演进守护进程 |
| | `evolver --review` | 交互式审查模式，变异后等待操作者确认 |
| | `evolver solidify` | 验证并固化已就绪的代码变异到 Git 仓库 |
| | `evolver session` | 开启或管理受控配对演进会话（支持假说记录） |
| **蜂群与监督**| `evolver mcp` | 启动基于 stdio 的 MCP 服务端（宿主接管入口） |
| | `evolver hitl` | 人在环中审批管理（`list` / `approve` / `reject`） |
| | `evolver supervise` | 人在环上动态监督（`status` / `pause` / `resume` / `veto`） |
| | `evolver setup-hooks` | 为当前工作区配置 Cursor / Claude Code 等 IDE 自动钩子 |
| **资产与知识**| `evolver skills` | 扫描、预览并同步外部 `SKILL.md` 到 GEP 资产库 |
| | `evolver gene-lifecycle`| 查看与维护基因状态（`active` / `under_review` / `retired`） |
| | `evolver episode` | 检索与展示历次自改进执行过程（Episode Record） |
| | `evolver self-report` | 触发 Autopoiesis 系统自检，更新活记忆与自生免疫规条 |
| **实验与评测**| `evolver experiment` | 运行严谨的受控消融实验（`--ablation`、`--placebo`） |
| | `evolver bench` | 执行冻结基准测试任务包、基线对比与配对二项检验 |
| | `evolver gate-report` | 输出验收门（Shadow Gate）的浸泡观察与转正评估报告 |
| | `evolver meta-report` | 输出系统底层演进机制遥测与后代变异质量报告 |
| **运维与服务**| `evolver check` / `watch` | 系统健康诊断与持续状态巡检 |
| | `evolver start` / `stop` | 跨平台系统级守护进程生命周期控制 |
| | `evolver webui` | 启动本地只读数据可视化看板（需 `server` 扩展） |
| | `evolver proxy` | 启动本地 A2A 协议代理服务（需 `server` 扩展） |

---

## 🔒 安全模型与工程护栏

`evolver.py` 具有自动修改代码并提交的能力，因此安全设计贯穿于每一个执行环节：

- **Git 爆炸半径防御**：所有变异操作严格绑定 Git 仓库。变异执行前自动通过 `git stash` 建立保护快照；每个基因均明确限定变异文件上限（`constraints.max_files`）与路径黑名单（`forbidden_paths`）。一旦检验失败或中断，系统自动执行无损回滚。
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
│   ├── asset_store.py      # 叠加式 JSON/JSONL 本地高性能存储
│   ├── hitl.py             # 人在环中（HITL）审批决策门
│   ├── supervision.py      # 人在环上（HOTL）实时监督与自动熔断
│   ├── skill_assets.py     # 外部技能生态桥接与蒸馏器
│   ├── gene_lifecycle.py   # 基因全生命周期流转与状态机治理
│   └── solidify.py         # 变异应用、安全验证与 Git 固化提交
├── bench/                  # 锚侧冻结任务包、评分器与统计检验套件
├── experiment/             # 受控消融裁决套件（双臂盲测、占位对照与充足性审计）
├── adapters/               # IDE 深度集成适配器（Cursor / Claude Code / Codex 等钩子）
├── proxy/                  # 本地 A2A 分布式代理与模型路由矩阵
└── webui/                  # 只读可视化仪表盘（嵌入式前端与 SSE 实时事件流）
```

---

## 📚 延伸阅读与开发指南

- **[演进方案.md](演进方案.md)**：现行最高章程，阐述自演进系统从“库即尺子”迈向“经验即证据”的完整论证。
- **[AGENTS.md](AGENTS.md)**：面向 AI 智能体开发者的行为准则、避坑指南与架构细节。
- **[DEBUG.md](DEBUG.md)**：深度调试手册，记录互锁排查、复杂边缘条件与稳定性实践。
- **[CHANGELOG.md](CHANGELOG.md)**：详细的版本演进记录与发布说明。
- **[CONTRIBUTING.md](CONTRIBUTING.md)**：代码贡献与测试规范指南。

---

## 📄 开源许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证开源发布。

> **关于谱系传承之说明**：`evolver.py` 是依据公开标准、测试契约与行为协议独立研发的 Python 净室实现。原始参考概念源自 EvoMap 组织，本项目在保持架构纯净与现代化的同时，以更加宽松、对工程友好的 Apache-2.0 协议独立分发。
