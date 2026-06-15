# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Python 3.12+ 移植版本**，源自 [`@evomap/evolver`](https://github.com/EvoMap/evolver) —— 一个基于 GEP（基因组进化协议）的 AI 智能体自进化引擎。

本移植目标是在使用现代 Python 工具链的同时，与 Node.js 参考实现（v1.89.3）达成**完全行为等价**：

- **Python 3.12+** — `asyncio`、类型参数语法（`list[str]`）、`tomllib`
- **uv** — 高速 Python 包管理
- **Pydantic v2** — 模式验证与配置
- **httpx** — 异步 HTTP 客户端（相当于 Node.js 的 `undici`）
- **FastAPI + uvicorn** — 本地代理与 WebUI

> **注意**：GEP 核心数据层、进化流水线、Proxy 路由与高级认知编排已基本可用。ATP 商业闭环、部分 Hub 资产路由及生产级验证者沙箱仍待完善。详见下方[实现状态](#实现状态)。

---

## 快速开始

```bash
# 安装依赖
uv sync

# 运行单次进化周期
uv run evolver

# 守护进程循环模式
uv run evolver --loop

# 审查模式
uv run evolver --review

# 启动 WebUI 仪表盘
uv run evolver webui

# 启动本地 A2A 代理
uv run evolver proxy
```

## 前置要求

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — 必需。Evolver 使用 git 进行回滚、爆炸半径计算和固化。在非 git 目录中运行将失败并显示明确错误信息。
- **[uv](https://docs.astral.sh/uv/)** — 推荐的包管理器。标准 `pip` 亦可使用。

## 项目结构

```
src/evolver/
├── cli.py              # CLI 入口（886 行）
├── config.py           # 环境变量与阈值
├── canary.py           # Fork 金丝雀：验证 CLI 可正常加载
├── evolve/
│   ├── runner.py       # 周期编排（单次 + 守护循环）
│   ├── guards.py       # 起飞前检查（负载、RSS、冷却）
│   ├── post_cycle.py   # 周期末钩子（ATP auto-buyer）
│   └── pipeline/       # 七阶段流水线 + preflight（异步函数）
│       ├── collect.py      # 日志扫描 + living_memory
│       ├── signals.py      # 信号 + guard/preflight/learning
│       ├── hub.py          # Hub 查询
│       ├── enrich.py       # memory_bridge 双向同步
│       ├── autopoiesis.py  # SelfReport + homeostasis
│       ├── select.py       # Gene/Capsule 选择
│       └── dispatch.py     # GEP 提示词 + solidify 状态
├── gep/                # GEP（基因组进化协议）核心
│   ├── schemas/        # Pydantic 模型：Gene、Capsule、Task、Protocol
│   ├── asset_store.py  # JSON/JSONL 持久化与叠加语义
│   ├── cognition.py    # 高级认知编排（回忆/探索/课程/反思）
│   ├── solidify.py     # 应用基因 → 验证 → 持久化 → 发布
│   ├── selector.py     # 信号匹配 + 表观遗传偏置
│   ├── signals.py      # 信号收集与分类
│   ├── validator/      # 沙箱执行器、报告器、质押引导
│   └── ...             # 55+ 模块
├── proxy/              # 本地 HTTP 代理（CLI 默认 8081；路由 /v1/a2a）
│   ├── server/routes.py    # FastAPI 路由（task/ATP/extensions）
│   ├── router/             # LLM 路由、特性开关、SSE 流式
│   ├── extensions/         # DM、会话、技能更新、追踪控制
│   ├── mailbox/store.py    # 本地邮箱 JSONL 存储
│   ├── sync/               # Hub 双向同步引擎
│   └── lifecycle/manager.py# 代理生命周期 + 心跳
├── atp/                # Agent 交易协议市场
│   ├── protocol.py         # 枚举与 Pydantic 模型
│   ├── auto_buyer.py       # 自动发现能力缺口
│   ├── auto_deliver.py     # 自动认领并交付任务
│   └── settlement.py       # 本地账本
├── adapters/           # IDE 集成钩子
│   ├── hook_adapter.py     # 共享适配器逻辑
│   ├── setup_hooks.py      # 为 Cursor、Claude Code 等安装钩子
│   └── scripts/            # 运行时脚本（session_start、signal_detect）
├── ops/                # 运维（生命周期、健康、自修复）
│   ├── lifecycle.py        # 跨平台守护进程管理
│   ├── health_check.py     # 磁盘/内存/进程检查
│   └── self_repair.py      # Git 紧急修复
└── webui/              # FastAPI 只读仪表盘
    ├── app.py            # 仪表盘 + SSE `/events/stream`
    ├── dashboard.py      # 暗色 HTML 仪表盘（实时事件）
    ├── client/           # 内嵌 JS/CSS（SSE、bootstrap、i18n）
    └── observer/         # 数据聚合模块

tests/                  # 130+ 测试文件，1250+ 用例（pytest）
scripts/                # 17 个 CLI 辅助脚本
assets/gep/             # 种子基因库
memory/                 # 运行时数据（graph JSONL、reviews JSONL）
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | 运行时数据目录 |
| `EVOLVER_REPO_ROOT` | 自动检测 | 覆盖仓库根目录 |
| `EVOLVE_STRATEGY` | `balanced` | 进化策略预设 |
| `EVOLVE_BRIDGE` | auto | Git worktree 变异桥接 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | 回滚策略：stash / hard / none |
| `EVOLVER_LOOP_INTERVAL_MS` | `60000` | 周期间隔（毫秒） |
| `EVOLVER_MAX_CYCLES` | `1000` | 单次运行最大周期数 |
| `EVOLVER_MUTATION_TIMEOUT_MS` | `300000` | 变异超时 |
| `EVOLVER_VALIDATOR_ENABLED` | `true` | 启用验证者守护进程 |
| `EVOLVER_ATP_DAILY_BUDGET` | `10` | ATP 每日预算 |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI 端口 |
| `EVOLVER_PROXY_PORT` | `8081` | 本地代理端口（`EVOMAP_PROXY_PORT` 别名）；可用 `evolver proxy --port` 覆盖 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | 自动生成 | 节点身份 |
| `GITHUB_TOKEN` | — | GitHub API 令牌 |
| `EVOLVER_FF_ENABLE_RECALL_INJECT` | `true` | 向 GEP 提示词注入已验证回忆 |
| `EVOLVER_FF_ENABLE_REFLECTION` | `true` | 固化后调优 personality |
| `EVOLVER_FF_ENABLE_EXPLORE` | `false` | AST 代码库探索信号 |
| `EVOLVER_FF_ENABLE_CURRICULUM` | `false` | 课程学习任务序列 |
| `EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE` | `false` | Proxy 技能自动更新后台循环 |

## 实现状态

> **总体评估**（2026-06-11）：**1250+ 测试通过**，**mypy strict 清零**。核心循环含 Autopoiesis + memory_bridge；ATP CLI 参数与 Proxy 端口统一为主要缺口。

| 子系统 | 状态 | 说明 |
|---|---|---|
| **GEP 数据层** | ~90% | `asset_store`、schemas、`solidify`、`sanitize`、`crypto` 生产级 |
| **GEP 高级认知** | ~75% | `cognition.py` 接线回忆/反思/蒸馏；探索/课程由 feature flag 控制 |
| **进化流水线** | ~90% | 7 阶段 + preflight + post_cycle；Autopoiesis 与 memory_bridge 已接线 |
| **Proxy 基础设施** | ~85% | 路由前缀 `/v1/a2a`；默认端口 8081；SSE LLM 中继 |
| **ATP 市场** | ~55% | 本地结算 + Proxy ATP 路由；CLI `buy`/`orders` 参数不完整 |
| **IDE 适配器** | ~65% | 4 个 IDE 模块 + 脚本；`setup-hooks` 仅 4 平台 |
| **Ops 运维** | ~75% | `lifecycle`、`health_check`、`skills_monitor`、`innovation`、`trigger` |
| **WebUI** | ~65% | Observer API、SSE 客户端、实时仪表盘；非完整 SPA |
| **验证者** | ~50% | 沙箱框架存在；生产级网络隔离待完善 |
| **Scripts** | 100% | `scripts/` 17/17 工具脚本已实现 |
| **测试覆盖** | ~79% | 129 个文件 vs Node.js 参考 ~164 个 |

详细差距分析见 [`设计方案.md`](设计方案.md) 和 [`TODO.md`](TODO.md)。

## 示例

| 示例 | 说明 |
|---|---|
| [`examples/hello-world/`](examples/hello-world/) | 在隔离工作区运行单次进化周期 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 下单/交付/心跳演示（可 mock Hub） |

## 测试

```bash
# 运行全部测试
uv run pytest tests/ -q

# 运行并生成覆盖率报告
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# 排除慢速测试（CI 默认）
uv run pytest -m "not slow"

# 代码检查
uv run ruff check src tests
uv run mypy src

# 验证所有模块导入
python scripts/validate_modules.py
```

## 脚本工具

| 脚本 | 用途 |
|---|---|
| `scripts/a2a_export.py` | 将资产导出为 A2A JSON |
| `scripts/a2a_ingest.py` | 导入 A2A 资产 |
| `scripts/extract_log.py` | 按时间/类型过滤 events.jsonl |
| `scripts/human_report.py` | 生成 Markdown 进化报告 |
| `scripts/generate_history.py` | GEP 事件时间线（Markdown） |
| `scripts/gep_append_event.py` | 手动追加 GEP 事件 |
| `scripts/recover_loop.py` | 守护循环恢复诊断 |
| `scripts/gep_personality_report.py` | 人格状态 HTML 报告 |
| `scripts/recall_verify_report.py` | 回忆/记忆图谱覆盖率报告 |
| `scripts/a2a_promote.py` | 候选基因晋升为正式基因 |
| `scripts/analyze_by_skill.py` | 按技能分析进化事件 |
| `scripts/build_binaries.py` | PyInstaller 独立可执行文件构建 |
| `scripts/check_changelog.py` | CHANGELOG 与版本号一致性检查 |
| `scripts/seed_merchants.py` | ATP 商家服务种子数据 |
| `scripts/suggest_version.py` | 语义化版本号建议 |
| `scripts/validate_modules.py` | 验证所有模块可导入 |
| `scripts/validate_suite.py` | 导入检查 + 快速 pytest 集成门禁 |

## 架构

### 进化流水线（6 阶段）

1. **Collect** — 读取 MEMORY.md、会话日志、系统健康状态
2. **Signals** — 从语料中提取可操作的信号
3. **Select** — 选择 Gene + Capsule（含表观遗传偏置）
4. **Enrich** — 用记忆建议、Hub 命中、平台检测增强上下文
5. **Hub** — 与 EvoMap Hub / 本地代理协调
6. **Dispatch** — 构建 GEP 提示词，写入固化状态

### 核心概念

- **Gene** — 可复用的突变策略（signals_match → execution_trace）
- **Capsule** — 带有结果的具体执行实例
- **Epigenetics** — 环境感知的基因抑制/激活
- **Solidify** — 将经验验证的突变应用到代码库
- **ATP** — Agent 交易协议，用于自主服务市场

## 与 Node.js 参考实现的差异

- **许可证**：Python 移植版使用 Apache-2.0；Node.js 参考实现使用 GPL-3.0-or-later
- **源码可见性**：Python 移植版完全可读；Node.js 核心文件经混淆保护
- **数据库**：Python 移植版增加了 `ops/sqlite_store.py` 用于 SQLite 持久化（增强）
- **Recipe Hub**：Python 移植版包含 `recipe/` 模块（新功能）
- **WebUI 前端**：Python 移植版提供内嵌 JS 客户端（`webui/client/`）与 SSE；非独立 SPA 构建

## 文档

- [`设计方案.md`](设计方案.md) — 综合设计文档（~1500 行）
- [`TODO.md`](TODO.md) — 详细差距分析与路线图
- [`AGENTS.md`](AGENTS.md) — Agent 集成指南、编码规范、常见陷阱
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 贡献指南
- [`SKILL.md`](SKILL.md) — Skill 使用参考

## 许可证

[Apache License 2.0](LICENSE)

> 这是 EvoMap evolver 引擎的社区移植版本。原始 Node.js 参考实现由 EvoMap 以 GPL-3.0-or-later 许可证分发。
