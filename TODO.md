# evolver.py 完善路线图（详尽版）

> 基于 `./evolver/` (Node.js 原版 **v1.90.0**，已出 v2.0.0-beta) 与 `./evolver.py/` (Python 移植版 v1.89.14) 的逐文件、逐函数、逐契约对比分析。
> 差距按 **CRITICAL / HIGH / MEDIUM / LOW** 四级标注。
> 优先级按 **P0 (阻塞发布) / P1 (核心功能) / P2 (增强体验) / P3 (锦上添花)** 排序。
> 每项任务均附 **验收标准 (DoD)**、**依赖关系**、**参考源文件**、**测试对标**。
>
> **2026-06-20 Sprint 9 更新**：对标版本从 v1.89.11 追平至 **v1.89.14**。
> 7 项差距（惰性基因禁用、节点密钥版本化、Hub 不可达退避、反滥用遥测心跳、结果上报模式、心跳强制更新、最后更新确认）已实现。
> 详细分析见 **[`演进方案.md`](演进方案.md)** Sprint 9 章节。
>
> **2026-07-06 Sprint 10 更新**：evolver/ 连发至 **v1.90.0**（并出 v2.0.0-beta.0/beta.1）。
> 本期单期增量最大（src/ +5668 行、test/ +13198 行），定位 **17 项差距**，最重者为：
> - **G10.1 多源轨迹导出**（trajectoryExport 测试 3316 行 + 9 专项）——蒸馏/归因数据底座，evolver.py 仅 81 行存根
> - **G10.2 Solo 模式**（`--solo` 受约束野性 / 断路器 + git 守卫）——全新 `solo/` 子系统
> - **G10.3 CLI Contracts**（`reuse`/`publish` v1，cliContracts 1190 行 + 测试 2021 行）——provenance/脱敏 gate/重签
> - **G10.4 GEP Recipe 组合**（skill2recipes，⚠️ 与现有模板 `recipe/` 同名异物）
> - **G10.5 Host Error Classifier (#571)**——4xx 宿主错误不误 ban 基因
> - G10.8/9 force-update 强化、outbound 韧性；G10.17 v2.0.0 单体化跟踪策略
>
> 详细分析与 6 周计划见 **[`演进方案.md`](演进方案.md)** Sprint 10 章节。

---

## 2026-06-15 审阅更新（第三轮：对标 v1.89.11 + Sprint 化）

> 触发：evolver/ 最近 4 周（05-18~06-15）发版 39 次（v1.84.1→v1.89.11），新增 execBridge、
> conversationSniffer、Hub 韧性 Round 3-9、多 Provider 路由等，本路线图此前未覆盖。
>
> | 维度 | v1.89.3 对标（上轮） | v1.89.11 对标（本轮） |
> |---|---|---|
> | 测试文件 | ~164 (Node) / 129 (Py) | **185** (Node) / 147 (Py) — 缺 38 |
> | 种子基因库 | 未审计 | **496 行(Node) vs 72 行(Py)** — 落后 6.9× |
> | 运行时 hooks | "完整" | **存根**（runtime_paths 20/416, session_start 31/281） |
> | Hub 韧性 | 部分 | **缺 Round 3-9**（8 个测试文件） |
> | 新增模块 | — | 🆕 execBridge、conversationSniffer、5 条多 Provider 路由 |
>
> **追赶策略**：按 `演进方案.md` 的 Sprint 0-8 推进，每 Sprint 末更新本表勾选状态。

---

## 2026-07-06 Sprint 10 增补（对标 v1.89.14 → v1.90.0）

> 触发：evolver/ 于 06-18~07-03 连发至 v1.90.0（+ v2.0.0-beta），src/ +5668 行 / test/ +13198 行，
> 单期增量最大。经 tag diff + 明文测试契约提取，定位 17 项差距。Sprint 1-8 经实测已基本落地
> （217 源文件 / 159 测试文件），故聚焦 v1.89.14 之后未覆盖增量。详见 **[`演进方案.md`](演进方案.md)** Sprint 10。

### S10-A 新增任务（P0/P1）

| 任务 | 优先级 | 目标 | DoD | 参考（测试即契约） |
|---|---|---|---|---|
| **G10.5** `gep/host_error_classifier.py` | **P0** ✅ **已完成** | 新建 ~50 行；`is_host_client_error()`+非全局正则；接入 `signals.py` | 4xx 宿主错误出 `host_llm_client_error`，**不**触发 ban_gene/failure_loop | `hostClientErrorSignals.test.js`(86) → `tests/gep/test_host_error_classifier.py`(5 用例) |
| **G10.2** `solo/`（`--solo`） | **P0** ✅ **已完成** | 新 `solo/breaker.py`+`solo/git_guard.py`；CLI `--solo`；runner/guards 接入 | 断网（覆盖 A2A_HUB_URL）+ 禁 Validator + 禁 ATP；banner 一致；新 env 接 config | `soloMode.test.js`(97) → `tests/solo/test_solo.py`(11 用例，含 subprocess 冒烟) |
| **G10.1** `gep/trajectory/` | **P0** 🟡 **Slice 1+2+3a 完成** | 新子包：`builder`/`io`/`crypto`/`sources`；`evolver trajectory` CLI | ✅ Slice 1+2+3a：builder(分组/turn/tool-call/provider 归一/语言/失败/stats) + io(原子/symlink/0600) + crypto(AES-GCM node-secret+keyring+RSA hub-key+回退+fail-closed) + **sources(Codex rollout + Claude Code transcript + OpenAI generic-chat 解析、源分类、test/edit/failure 检测)** + **全流式 tool-arg 重建（Anthropic/OpenAI Chat+snapshot 去重/OpenAI Responses）** + CLI 自动检测 session/proxy+目录递归；27 用例。⏳ Slice 3b 余项：Cursor vscdb(SQLite)、Gemini、Kimi（bespoke 低频源） | `trajectoryExport.test.js`(3316) + 9 专项 → `tests/gep/trajectory/`(27) |
| **G10.3** `gep/cli_contracts.py` | **P1** | 统一 `reuse`/`publish` v1：provenance + 脱敏 gate + 重哈希重签 + 幂等 | 2021 行测试逐条对标 | `cliContracts.test.js`(2021) |
| **G10.8** `force_update.py` 强化 | **P1** ✅ **已完成** | 212→≥500：failure codes、keep-list、mid-copy wedge、concurrency guard、idempotent | sentinels(BUSY/NOOP) + 模块级 mutex(finally) + 幂等 floor(操作符/v 归一化、反降级) + 冻结 coded failures + Zip Slip 安全解压 | 5 个 forceUpdate 测试 → `test_force_update.py`(+19 用例) |
| **G10.9** `proxy/sync/outbound.py` | **P1** ✅ **已完成** | 91→≥250：批量重试、离线恢复、指数退避 | body-size 分批 + 413 隔离/退避 + retryable/terminal + trace 门控 + 脱敏；`store.defer`/`next_retry_at` | `proxyOutboundSync.test.js`(+429) → `tests/test_proxy_outbound_sync.py`(11 用例) |
| **G10.4** `gep/skill2recipes.py` + `skill2gep_audit.py` | **P1** | Skill→GEP Recipe 组合（manifest: steps/optional/condition/price）；保留现有模板 `recipe/`，命名分离 | manifest 解析 + 每步 validation allow-list + publish/dry-run | `skill2recipes.test.js`(212)+`recipeHub` |

### S10-B 深化任务（P2）

| 任务 | 目标 | 参考 |
|---|---|---|
| **G10.6** `proxy/client_settings.py`（405） | 客户端设置层（区别 `server/settings`） | `proxy/clientSettings.js` |
| **G10.7** `proxy/mailbox/state.py`（207） | mailbox 元数据状态机（与 store 分离） | `proxy/mailbox/state.js` |
| **G10.10** `ops/lifecycle.py` 358→≥550 | proxy health 接入 | `lifecycleProxyHealth.test.js`(279) |
| **G10.11** manager 深化 | stale node secret / token reuse / Round3-9 收尾 | manager 已 778，查漏补缺 |
| **G10.12** `oauth_login.py` 117→≥300 | OAuth 设备码流深化 | `oauthLogin.test.js`(+488) |
| **G10.13** `skill2gep.py` 435→≥600 | 反蒸馏再深化 | `skill2gep.test.js`(+240) |
| **G10.14** `session_start.py` 211→≥300 | 工作区作用域深化 | `sessionStartScope.test.js`(+151) |

### S10-C 数据 / 跟踪（P3）

- **G10.16** Sentinel arena rollout Gene (#586) 入 `genes.seed.json`。
- **G10.17** v2.0.0 单体化跟踪策略：v2.0.0 正式版后 src/ 不再存在，跟踪源切为 **`test/*.test.js` + index.js 行为契约**；本 Sprint 末把当前可读 src/ 契约固化进 `演进方案.md`。

### Sprint 10 验收（声称等价 v1.90.0）

- [ ] G10.1 trajectory export 五源 + 加密/脱敏/原子写/fails-closed 测试通过
- [ ] G10.2 `--solo` 三平台断网 + 禁 Validator/ATP
- [x] G10.3 reuse/publish 核心+扩展契约（`cli_contracts.py` + CLI + **39** 项测试：provenance/hash/auth/leak/credits/rehash-resign/OAuth-only）；剩余 ~27 项 Node 测试待移植
- [ ] G10.4 skill2recipes 与现有 recipe/ 命名不冲突
- [ ] G10.5 host 4xx 不误 ban 基因
- [ ] G10.8/9 force-update/outbound 测试对标
- [ ] 回归：`uv run pytest` / `ruff check` / `mypy src` 全绿，0 回归

---

## 2026-06-11 审阅更新（第二轮：文档对齐代码）

> 全量审计：CLI / Proxy 路径与端口 / 流水线 7 阶段 / Autopoiesis P4 / WebUI API / 双轨 feature flags。

### 当前健康度

| 指标 | 状态 | 说明 |
|---|---|---|
| 单元/集成测试 | ✅ 1250+ passed | 含 autopoiesis、memory_bridge、signals_preflight、webui insights |
| Mypy strict | ✅ 0 errors | `uv run mypy src` |
| Proxy routes | ✅ 已接线 | 前缀 `/v1/a2a`；CLI 默认端口 **8081**（非文档旧称 19820） |
| Autopoiesis | ✅ 端到端 | living_memory ↔ memory_graph 双向同步 + preflight 恢复 |
| 文档 | ✅ 2026-06-11 二轮 | README/SKILL/AGENTS/TODO 按代码实现修订 |

### 自上次路线图以来已完成（✅）

| 模块 | 状态 |
|---|---|
| `proxy/router/*` | model_router、features、cache_passthrough、messages_route（含 Anthropic/Bedrock SSE） |
| `proxy/extensions/*` | session/dm/skill_updater/trace_control + SkillUpdateLoop；已接入 proxy lifespan |
| `proxy/task/monitor.py` | 实现完整；routes 已接线 |
| `gep/cognition.py` | recall/reflection/distill 编排；explore/curriculum 由 flag 控制 |
| `ops/skills_monitor.py`、`innovation.py`、`trigger.py` | 完整 + 测试 |
| `adapters/claude_code.py`、`codex.py`、`kiro.py`、`opencode.py` | 完整 + 测试 |
| `atp/default_handler.py` | 完整 + 测试 |
| `webui/observer/*` | 10 模块 + 专项测试 |
| `webui/client/*` | 内嵌 JS/CSS 轻量仪表盘（无 SPA） |
| `gep/learning_signals.py`、`privacy_client.py` | 新增 + 测试 |
| `gep/validator/*` | ValidatorDaemon + sandbox 框架；生产级网络隔离仍缺 |

### 修订后优先级（接下来 4 周）

| 优先级 | 任务 | 理由 |
|---|---|---|
| ~~**P0**~~ | ~~CLI ATP argparse + Proxy 端口 8081~~ | ✅ `resolve_proxy_port` / `proxy_local_url` |
| ~~**P1**~~ | ~~`setup-hooks` 全线 adapter（含 cursor/claude-code）~~ | ✅ |
| ~~**P1**~~ | ~~GEP vs Proxy feature flags 对齐~~ | ✅ Proxy 委托 `gep/feature_flags` |
| **P2** | Hub ATP 商业闭环生产验证 | 本地状态机已通，Hub E2E 待验 |
| ~~**P2**~~ | ~~WebUI `app.py` / `server/http.py` 双栈收敛~~ | ✅ `create_app()` |
| **P2** | Validator 生产级网络隔离 | sandbox 框架已有 |
| **P3** | ~~Proxy task/ATP 路由接线~~ | ✅ 已完成 |
| **P3** | ~~webui SSE + memory sync 面板~~ | ✅ 已完成 |
| **P3** | ~~Autopoiesis P4 memory_bridge~~ | ✅ 已完成 |
| ~~**P3**~~ | ~~preflight 恢复期一次性 skip_hub~~ | ✅ `preflight_abort_recovery` → `skip_hub_calls` |
| ~~**P3**~~ | ~~`issue_reporter` 接入 post_cycle~~ | ✅ 每周期扫描 memory_graph |

### 仍属占位/浅实现（需继续）

- GEP 高级认知深化（LLM 蒸馏、课程学习自动出题）→ 基础编排已接线
- ~~`skill_updater` Hub 技能 zip 解压~~ → ✅ httpx 下载 + zipfile 解压
- Hub 端到端 ATP 商业闭环生产验证

---

## 执行摘要

Python 移植版成功复现了 **GEP 核心数据层**（schemas、asset_store、signals 基础提取）和 **完整进化循环**（runner + 7 阶段 pipeline + Autopoiesis + post_cycle），但在以下维度仍存在**结构性差距**（较初版路线图已显著收窄）：

| 维度 | Node.js 状态 | Python 状态 | 差距评估 | 风险等级 |
|---|---|---|---|---|
| **核心 GEP 协议** | 完整 + 20+ 高级模块 | ~55 模块，数据层生产级 | **~25% 差距** — 表观遗传、部分 distill LLM 路径待深化 | MEDIUM |
| **ATP 市场** | 完整商业闭环（14 文件） | 15 文件，缺口下单 + 默认交付 | **~45% 差距** — Hub 端到端商业闭环待验证 | MEDIUM |
| **A2A Proxy** | 生产级代理（23 文件） | ~19 文件，核心路由已接线 | **~20% 差距** — 高级 Bedrock 特性等待实现 | LOW |
| **IDE 适配器** | 运行时 hooks + 动态注入（13 文件） | 13 文件（4 IDE + scripts） | **~30% 差距** — 动态注入深度、脚本覆盖待扩展 | MEDIUM |
| **运维/生命周期** | 跨平台守护进程管理（10 文件） | 10 文件 | **~25% 差距** — 与 Node 版运维脚本数量仍有差 | LOW |
| **验证者系统** | 沙箱执行 + 质押 + 报告（4 文件） | 4 文件 + daemon 测试 | **~50% 差距** — 生产级网络隔离待完善 | HIGH |
| **高级 GEP 认知** | 课程/探索/反思/回忆注入（~25 文件） | `cognition.py` 编排 + 各子模块 | **~25% 差距** — explore/curriculum 默认关；LLM distill 待深化 | MEDIUM |
| **自动化运维** | 自 PR / Issue 报告 / 任务接收（~10 文件） | 文件存在，部分为浅实现 | **~50% 差距** — self_pr、issue_reporter 等待深化 | MEDIUM |
| **测试覆盖** | ~164 个测试文件 | ~129 个测试文件，1206 用例 | **~21% 差距** — messages_route SSE、cognition 已有专项测试 | MEDIUM |
| **文档/示例** | 多语言 README + SKILL.md + 17 个脚本 | 中英 README + 17 脚本 + 2 examples | **~25% 差距** — 距 Node 多语言 README 仍有差 | LOW |

**按模块统计**：

| 模块 | Node.js 文件数 | Python 文件数 | 差距文件数 | 严重程度 |
|---|---|---|---|---|
| `adapters/` | 13 (8 + 5 scripts) | 9 (5 + 4 scripts) | **4** | CRITICAL |
| `atp/` | 14 | 15 | **1 (default_handler)** | CRITICAL |
| `ops/` | 10 | 10+ | **~0** | LOW |
| `proxy/` | 23 | 21+ | **~2** | LOW |
| `webui/` | 30 (含 observer/client) | 22+ | **~8** | MEDIUM |
| `gep/` (高级) | ~80 | ~55 | **~25** | HIGH |
| `scripts/` | 18 | 17 | **1** | LOW |
| `examples/` | 2 | 2 | ✅ 对齐 | — |
| **总计** | **~172** | **~145** | **~35 (实质功能差距更大)** | — |

---

## 依赖关系图（简化）

```
P0 基础设施层
├── ops/lifecycle.py          ← 所有守护进程功能的前提
├── proxy/lifecycle/manager.py ← ATP/同步/心跳的前提
├── proxy/mailbox/store.py     ← 所有 Hub 交互的前提
├── adapters/hook_adapter.py   ← 所有 IDE 集成的前提
│
P1 核心功能层
├── atp/*                      ← 依赖 proxy/mailbox, proxy/sync
├── proxy/sync/*               ← 依赖 proxy/mailbox, proxy/lifecycle
├── proxy/router/*             ← 依赖 proxy/server
├── proxy/extensions/*         ← 依赖 proxy/router
├── ops/health_check.py        ← 依赖 ops/lifecycle
├── ops/self_repair.py         ← 依赖 ops/lifecycle
├── gep/validator/*            ← 依赖 gep/solidify, ops/health_check
├── gep/auto_distill_*.py      ← 依赖 gep/distill, gep/asset_store
├── gep/recall_*.py            ← 依赖 gep/memory_graph, gep/prompt
├── gep/reflection.py          ← 依赖 gep/memory_graph, gep/personality
├── gep/self_pr.py             ← 依赖 gep/solidify, gep/policy_check
├── gep/issue_reporter.py      ← 依赖 gep/env_fingerprint
│
P2 增强体验层
├── webui/observer/*           ← 依赖 gep/*, proxy/*
├── webui/client/*             ← 依赖 webui/observer
├── gep/portable.py            ← 依赖 gep/asset_store
├── gep/privacy_client.py      ← 依赖 gep/crypto
├── force_update.py            ← 依赖 ops/lifecycle
│
P3 打磨层
├── tests/*                    ← 依赖对应功能模块
├── scripts/*                  ← 依赖 gep/*, atp/*
├── README.i18n.md             ← 依赖功能完整度
```

---

## P0 — 阻塞发布（必须先完成才能声称"功能等价"）

### P0.1 验证者系统（Validator）

**参考**: `evolver/src/gep/validator/` (4 个文件)

> Node.js 版默认启用验证者模式，从 EvoMap Hub 拉取验证任务，在隔离沙箱中执行，提交验证报告并支持质押引导。Python 版完全缺失，导致无法参与去中心化验证网络。

#### P0.1.1 `evolver/gep/validator/__init__.py` — 验证者守护进程主入口
- **当前状态**: 文件已存在（279 行），`ValidatorDaemon` 类框架已搭建。
- **需完善**: 轮询 Hub `/a2a/validator/tasks`，认领任务，调度沙箱执行，提交报告。
- **关键行为**:
  - 启动时读取 `EVOLVER_VALIDATOR_ENABLED`（默认 ON）
  - 心跳上报验证者状态（`validator_heartbeat` 事件）
  - 任务轮询间隔：30s，支持指数退避
  - 并发控制：同时最多运行 `MAX_CONCURRENT_VALIDATIONS`（默认 3）个沙箱
  - 优雅关闭：收到 SIGTERM 时等待当前验证完成，超时 60s 强制终止
- **DoD**:
  - [x] `ValidatorDaemon` 类框架存在
  - [ ] `ValidatorDaemon.start()` / `.stop()` / `.is_running()` 完全可用
  - [ ] 单元测试覆盖：正常任务认领、空队列、Hub 500 退避、并发限制、优雅关闭
- **依赖**: `gep/a2a_protocol.py`, `gep/asset_store.py`
- **测试对标**: `test/validatorDaemon.test.js`

#### P0.1.2 `evolver/gep/validator/sandbox_executor.py` — 沙箱执行器
- **当前状态**: 文件已存在，基础框架搭建。
- **功能**: 在隔离环境中运行验证任务，防止恶意代码执行。
- **安全模型**（需完全复刻 Node.js 版）：
  - 验证命令白名单：仅允许 `python <script>` 前缀（**明确禁止 `pip`、`python -c`、`eval()`、`exec()`、`__import__`**）
  - 禁止 shell 操作符（`;`、`&`、`|`、`>`、`$()`、反引号）
  - 超时：180s（`EVOLVER_VALIDATION_TIMEOUT_MS`）
  - cwd 限制：临时目录，任务完成后自动清理
  - 资源限制：可选 `resource.setrlimit` 限制 CPU/内存（Linux）
  - 网络隔离：可选 `unshare` 或 `firejail`（Linux），Windows 回退到受限用户
- **DoD**:
  - [x] 基础文件存在
  - [ ] 正常脚本执行通过并返回 stdout/stderr/exit_code
  - [ ] 命令注入测试全部失败（`test_sandbox_security_injection`）
  - [ ] 超时测试：无限循环脚本在 180s 后被 SIGKILL
  - [ ] 资源泄漏测试：临时目录清理无残留
- **依赖**: `gep/sanitize.py`
- **测试对标**: `test/sandboxExecutor.security.test.js`, `test/validatorDaemon.test.js`

#### P0.1.3 `evolver/gep/validator/reporter.py` — 验证报告提交
- **功能**: 将沙箱执行结果格式化为验证报告，提交到 Hub。
- **报告格式**:
  ```json
  {
    "task_id": "...",
    "validator_node_id": "...",
    "status": "passed|failed|error|timeout",
    "score": 0..1,
    "execution_log": "...",
    "execution_time_ms": 1234,
    "sandbox_version": "..."
  }
  ```
- **DoD**:
  - [ ] 报告格式通过 Hub schema 验证
  - [ ] 网络失败时本地队列，恢复后批量重试
- **依赖**: `gep/validator/sandbox_executor.py`

#### P0.1.4 `evolver/gep/validator/stake_bootstrap.py` — 质押引导
- **功能**: 新验证者首次加入网络时的质押流程。
- **DoD**:
  - [ ] 生成质押交易请求
  - [ ] 指引用户完成链上质押
  - [ ] 质押确认后激活验证者身份
- **测试对标**: `test/stakeBootstrap.test.js`

---

### P0.2 A2A Proxy 生产级重构

**参考**: `evolver/src/proxy/` (23 个文件)

> Python 版 `proxy/` 已具备基础基础设施：`mailbox/store.py`（453 行，较完整）、`sync/engine.py`（147 行）、`lifecycle/manager.py`（410 行）、`server/routes.py`（474 行，35+ 路由已定义）。但 `router/`、`extensions/`、`trace/` 完全为空或缺失；`/asset/fetch`、`/asset/search`、LLM 中继等核心路由返回 `not_implemented`。Node.js 版是一个完整的本地代理基础设施，是 ATP、同步、LLM 中继的基石。

#### P0.2.1 `evolver/proxy/lifecycle/manager.py` — 代理生命周期管理器
- **功能**: 管理 Proxy 与 Hub 的全生命周期交互。
- **关键行为**:
  - `hub_hello()`: 启动时向 Hub 注册，获取节点 token 和特性标志
  - `heartbeat_loop()`: 每 `HEARTBEAT_INTERVAL_MS`（默认 6min）发送心跳，携带节点状态
  - `reauth()`: 收到 401/403 时自动重新认证
  - `feature_flags_poll()`: 轮询 Hub 获取动态特性开关
  - `register_wake_hook()`: 系统睡眠唤醒后恢复状态
  - `poke_heartbeat_loop()`: 外部触发立即心跳
- **状态机**:
  ```
  UNINITIALIZED → HELLO_SENT → AUTHENTICATED → HEARTBEATING
                        ↓            ↓
                   ERROR_BACKOFF ← UNAUTHORIZED
  ```
- **DoD**:
  - [x] 正常启动流程：hello → auth → heartbeat
  - [x] 401 触发 reauth，3 次失败后进入 ERROR_BACKOFF（最大 5min）
  - [x] Node Secret 版本化（Gap 2）：`parse_node_secret_version()`、`node_secret_version` 属性（store > env）、stale 检测
  - [x] Hub-Unreachable 指数退避（Gap 3）：`_record_hub_unreachable()` / `_record_hub_reachable()` / `_hub_unreachable_wait_ms()`
  - [x] 反滥用遥测心跳信封（Gap 4）：heartbeat `meta.anti_abuse` 注入
  - [x] 心跳强制更新（Gap 6）：`_maybe_trigger_force_update_from_heartbeat()` 含冷却
  - [x] 最后更新确认（Gap 7）：`read_pending_last_update()` / `set_pending_last_update()`
  - [ ] 网络断开后自动恢复，不丢失 outbound 队列消息
  - [ ] macOS 睡眠唤醒后检测到时钟跳变，立即发送恢复心跳
- **依赖**: `gep/a2a_protocol.py`, `gep/config.py`

#### P0.2.2 `evolver/proxy/mailbox/store.py` — 本地邮箱存储
- **功能**: 基于 SQLite + JSONL 的本地消息持久化，缓冲所有 Hub 流量。
- **数据模型**:
  - `messages.jsonl`: 所有入站/出站消息的追加日志
  - `state.json`: 邮箱元数据（last_poll_id, unread_count, version）
  - 内存索引：消息 ID → 文件偏移，支持 O(1) 查找
- **API**:
  - `send(envelope) -> msg_id`
  - `poll(type=None, since=None, limit=100) -> list[Envelope]`
  - `ack(msg_ids) -> int`
  - `list(type=None, status='all') -> list[Envelope]`
  - `delete(msg_ids) -> int`
- **并发安全**:
  - 写操作使用 `filelock.FileLock`（`messages.jsonl.lock`）
  - 读操作无锁（单 writer 假设）
  - 批量写入：积攒 50ms 内的写请求，一次性 fsync
- **DoD**:
  - [ ] 10k 消息读写性能 < 1s
  - [ ] 并发写入 100 线程无数据损坏
  - [ ] 崩溃恢复：重启后能正确读取所有未 ack 消息
  - [ ] 磁盘满时优雅降级：停止写入，记录 error 事件
- **依赖**: `gep/crypto.py`（可选加密敏感消息）
- **测试对标**: `test/mailboxStore.test.js`

#### P0.2.3 `evolver/proxy/sync/engine.py` + `inbound.py` + `outbound.py` — 同步引擎
- **功能**: 代理与 Hub 之间的双向同步，支持离线模式。
- **Outbound** (`outbound.py`):
  - 从 mailbox store 读取未发送消息
  - 批量 POST 到 Hub `/a2a/batch`
  - 成功则 ack，失败则指数退避重试
  - 离线检测：连续 3 次失败标记为 `OFFLINE`，停止重试直到网络恢复
- **Inbound** (`inbound.py`):
  - 长轮询 Hub `/a2a/events`（SSE 或 HTTP long-polling）
  - 接收事件后写入 mailbox store
  - 事件类型：task_assigned, message, skill_update, feature_flag_changed, force_update
- **SyncEngine** (`engine.py`):
  - 启动 outbound loop（`asyncio.Task`）和 inbound loop
  - 在线/离线状态广播（影响 ATP 自动买卖决策）
  - 优雅关闭：取消两个 loop，等待 inflight 请求完成
- **DoD**:
  - [ ] 正常在线模式：消息端到端延迟 < 2s
  - [ ] 离线模式：消息本地队列，网络恢复后自动批量发送
  - [ ] 高负载测试：1000 消息/秒 outbound 不丢失
  - [ ] 内存泄漏测试：连续运行 1 小时，内存增长 < 10MB
- **依赖**: `proxy/mailbox/store.py`, `proxy/lifecycle/manager.py`
- **测试对标**: `test/syncEngineLoopResilience.test.js`

#### P0.2.4 `evolver/proxy/server/routes.py` — 完整 REST 路由矩阵
- **功能**: FastAPI 路由，暴露所有 Proxy 本地 API。
- **路由表**（完全复刻 Node.js 版 `server/routes.js`）：

| 类别 | 方法 | 路径 | 说明 |
|---|---|---|---|
| Mailbox | POST | `/mailbox/send` | 发送消息到 Hub |
| Mailbox | POST | `/mailbox/poll` | 轮询新消息 |
| Mailbox | POST | `/mailbox/ack` | 确认消息已处理 |
| Mailbox | GET | `/mailbox/list` | 列出消息 |
| Mailbox | GET | `/mailbox/status/{id}` | 查询消息状态 |
| Assets | POST | `/asset/validate` | 验证资产格式 |
| Assets | POST | `/asset/fetch` | 从 Hub 获取资产 |
| Assets | POST | `/asset/search` | 语义搜索资产 |
| Assets | POST | `/asset/submit` | 提交资产到 Hub |
| Assets | GET | `/asset/submissions` | 列出本地提交 |
| Tasks | POST | `/task/subscribe` | 订阅任务类型 |
| Tasks | POST | `/task/unsubscribe` | 取消订阅 |
| Tasks | GET | `/task/list` | 列出可用任务 |
| Tasks | POST | `/task/claim` | 认领任务 |
| Tasks | POST | `/task/complete` | 提交任务结果 |
| Tasks | GET | `/task/metrics` | 任务统计 |
| DM | POST | `/dm/send` | 发送直接消息 |
| DM | POST | `/dm/poll` | 轮询 DM |
| DM | GET | `/dm/list` | 列出 DM |
| Session | POST | `/session/create` | 创建会话 |
| Session | POST | `/session/join` | 加入会话 |
| Session | POST | `/session/leave` | 离开会话 |
| Session | POST | `/session/message` | 发送会话消息 |
| Session | POST | `/session/delegate` | 委派会话权限 |
| Proxy | GET | `/proxy/status` | 代理状态 |
| Proxy | GET | `/proxy/hub-status` | Hub 连接状态 |
| ATP | POST | `/atp/order` | 创建订单 |
| ATP | POST | `/atp/deliver` | 提交交付 |
| ATP | POST | `/atp/verify` | 验证交付 |
| ATP | POST | `/atp/settle` | 结算订单 |
| ATP | POST | `/atp/dispute` | 发起争议 |
| ATP | GET | `/atp/merchant/tier` | 查询商家等级 |
| ATP | GET | `/atp/order/{order_id}` | 查询订单 |
| ATP | GET | `/atp/proofs` | 列出证明 |
| ATP | GET | `/atp/policy` | 查询 ATP 政策 |
| LLM | POST | `/v1/messages` | Anthropic/Bedrock 代理 |

- **认证**: 所有路由（除 `/proxy/status`）需要 `Authorization: Bearer <token>`
- **Token 来源**: `~/.evomap/proxy-token` 或环境变量 `EVOMAP_PROXY_TOKEN`
- **DoD**:
  - [ ] 上述 35+ 路由全部实现并通过集成测试
  - [ ] Bearer token 认证失败返回 401，格式错误返回 400
  - [ ] 路由参数验证使用 Pydantic 模型
  - [ ] SSE 流式响应（`/task/subscribe`, `/session/message`）支持 `text/event-stream`
- **依赖**: `proxy/lifecycle/manager.py`, `proxy/mailbox/store.py`, `proxy/sync/engine.py`
- **测试对标**: `test/proxyServer.test.js`, `test/proxyAssetSearchPlan.test.js`, `test/proxySettings.test.js`

#### P0.2.5 `evolver/proxy/router/messages_route.py` — LLM 消息路由器
- **功能**: `/v1/messages` 路由的上游代理，支持 Anthropic 和 AWS Bedrock 双上游。
- **Anthropic 模式**:
  - 转发到 `api.anthropic.com/v1/messages`
  - 保留 `stream` 参数，支持 SSE 透传
  - Token 中介：Proxy 的 `Authorization` 用于自身认证，上游使用独立 `ANTHROPIC_API_KEY`
- **Bedrock 模式** (`EVOMAP_UPSTREAM=bedrock`):
  - 模型 ID canonicalize：`claude-3-7-sonnet-20250219` → `anthropic.claude-3-7-sonnet-20250219-v1:0`
  - Body 转换：删除 `stream` 字段，处理 `thinking` type
  - SigV4 签名（`boto3` 或 `botocore`）
  - AWS event-stream → 标准 SSE 转换
- **DoD**:
  - [ ] Anthropic 流式响应延迟 < 100ms（首 token）
  - [ ] Bedrock 模型 ID 映射表与 Node.js 版一致
  - [ ] 上游 5xx 时返回 502 并带 Retry-After
  - [ ] Token 不泄漏：上游请求头中无 Proxy token
- **依赖**: `proxy/server/routes.py`
- **测试对标**: `test/proxyAnthropic.test.js`, `test/proxyBedrock.test.js`, `test/proxyStreaming.test.js`, `test/proxyTokenReuse.test.js`

#### P0.2.6 `evolver/proxy/router/model_router.py` — 模型路由逻辑
- **功能**: 根据请求中的模型名、特性标志、用户 tier，选择最优上游和模型。
- **DoD**:
  - [ ] 默认模型 fallback 逻辑
  - [ ] 特性标志热切换模型（无需重启 Proxy）
  - [ ] 降级保护：高 tier 用户不会意外降级到 cheap 模型
- **测试对标**: `test/routerNoDowngrade.test.js`, `test/routerDegenerateTiers.test.js`

#### P0.2.7 `evolver/proxy/router/features.py` — 特性路由
- **功能**: 根据 Hub 下发的特性标志，动态启用/禁用路由。
- **DoD**:
  - [ ] 特性标志变更后 30s 内生效
  - [ ] 禁用路由返回 503 Service Unavailable
- **测试对标**: `test/routerFeatureFlag.test.js`, `test/routerFeatures.test.js`

#### P0.2.8 `evolver/proxy/router/cache_passthrough.py` — 缓存透传
- **功能**: 对 LLM 请求的缓存命中优化。
- **DoD**:
  - [ ] 相同请求（system + messages 哈希）缓存 5min
  - [ ] 缓存键排除 temperature/top_p 等随机参数
- **依赖**: `proxy/router/messages_route.py`

#### P0.2.9 `evolver/proxy/server/settings.py` — 代理设置持久化
- **功能**: 保存和读取 Proxy 配置。
- **DoD**:
  - [ ] 支持设置 Hub URL、token、上游偏好
  - [ ] 原子写入（temp file + rename）
- **测试对标**: `test/proxySettings.test.js`

#### P0.2.10 `evolver/proxy/extensions/dm_handler.py` — 直接消息处理器
- **功能**: 处理 Hub 下发的 DM（直接消息），触发本地动作。
- **DoD**:
  - [ ] 解析 DM 类型（command、notification、request）
  - [ ] command 类型 DM 执行对应 CLI 命令
- **依赖**: `proxy/sync/inbound.py`

#### P0.2.11 `evolver/proxy/extensions/session_handler.py` — 会话处理器
- **功能**: 管理多 Agent 会话的创建、加入、消息转发。
- **DoD**:
  - [ ] 支持创建/加入/离开会话
  - [ ] 会话消息广播到所有参与者
  - [ ] 会话委派权限转移

#### P0.2.12 `evolver/proxy/extensions/skill_updater.py` — 技能更新器
- **功能**: 轮询 Hub 技能更新，自动下载并应用。
- **DoD**:
  - [x] 检测到技能新版本后自动 `evolver fetch <query>`（`process_updates` + `install_from_hub`）
  - [x] 更新失败时回滚到旧版本
  - [x] 支持手动禁用自动更新
  - [x] Hub `/skills/updates` 轮询 + mailbox `skill_update` 回退

#### P0.2.13 `evolver/proxy/extensions/trace_control.py` — 追踪控制器
- **功能**: 响应 Hub 的追踪指令，动态调整日志级别和追踪范围。
- **DoD**:
  - [x] 支持启用/禁用特定模块的 debug 日志
  - [x] 支持生成追踪报告并上传到 Hub（`enable_trace_upload` feature flag 控制）

#### P0.2.14 `evolver/proxy/task/monitor.py` — 任务监控
- **功能**: 追踪已认领任务的状态，上报心跳元数据。
- **DoD**:
  - [ ] 任务超时预警（到期前 10min 警告）
  - [ ] 任务统计：已完成、已放弃、进行中
- **测试对标**: `test/taskMonitor.test.js`

---

### P0.3 ATP 市场完整实现

**参考**: `evolver/src/atp/` (14 个文件)

> Node.js 版拥有完整的 Agent Transaction Protocol（代理交易协议）实现，支持自动消费、自动商家交付、争议仲裁。Python 版 `protocol.py`（153 行，枚举与 Pydantic 完整）、`settlement.py`（本地账本较完整）、`hub_client.py` / `consumer_agent.py` / `merchant_agent.py` 等文件已存在，但 `auto_buyer.py` / `auto_deliver.py` 核心决策逻辑为 `pass`，`default_handler.py` 缺失，无法完成真实交易闭环。

#### P0.3.1 `evolver/atp/protocol.py` — ATP 线协议完整化
- **当前状态**: 仅有 `ProofStatus`, `ExecutionMode` 等基础枚举。
- **需补充**:
  - `VerifyMode`: `strict`, `lenient`, `auto`
  - `RoutingMode`: `direct`, `proxy`, `relay`
  - `OrderStatus`: `pending`, `confirmed`, `delivered`, `verified`, `settled`, `disputed`, `cancelled`, `refunded`
  - `Role`: `consumer`, `merchant`, `validator`, `judge`
  - `ServiceCategory`: `skill`, `compute`, `data`, `verification`
  - Pydantic 模型：`Order`, `Delivery`, `Proof`, `Dispute`, `Settlement`, `ServiceListing`
- **DoD**:
  - [ ] 所有枚举与 Node.js 版数值一致（保证跨语言互操作）
  - [ ] Pydantic 模型通过 `extra="forbid"` 严格验证
- **依赖**: `gep/schemas/capsule.py`

#### P0.3.2 `evolver/atp/hub_client.py` — Hub 客户端完整接口
- **功能**: 封装所有 ATP Hub HTTP 调用。
- **API 列表**:
  - `place_order(service_id, budget, requirements) -> Order`
  - `submit_delivery(order_id, proof, result_asset_id) -> Delivery`
  - `verify_delivery(delivery_id, verdict, score) -> Verification`
  - `settle_order(order_id) -> Settlement`
  - `dispute_order(order_id, reason, evidence) -> Dispute`
  - `get_order_status(order_id) -> OrderStatus`
  - `get_atp_policy() -> Policy`
  - `list_my_tasks() -> list[Task]`
  - `get_merchant_tier(merchant_id) -> Tier`
  - `list_proofs(order_id) -> list[Proof]`
  - `publish_service(service) -> ServiceListing`
- **DoD**:
  - [ ] 所有 API 支持通过 Proxy 路由（`http://127.0.0.1:19820/atp/...`）
  - [ ] 网络失败时本地队列，指数退避重试
  - [ ] 响应超时 30s，重试 3 次
- **依赖**: `atp/protocol.py`, `proxy/server/routes.py`（用于本地透传）

#### P0.3.3 `evolver/atp/auto_buyer.py` — 自动消费代理
- **功能**: 自主发现能力缺口，自动下单购买服务。
- **关键逻辑**:
  - 能力缺口 → ATP 服务搜索 → 预算评估 → 下单
  - 每日预算上限（`EVOLVER_ATP_DAILY_BUDGET`，默认 10 ATP）
  - 每单预算上限（`EVOLVER_ATP_PER_ORDER_BUDGET`，默认 5 ATP）
  - 去重：同一服务 24h 内不重复购买
  - 同意确认：首次运行生成 `~/.evomap/atp-consent` 文件，记录用户同意
  - 冷启动安全：前 10 单必须人工确认（`EVOLVER_ATP_AUTO_BUY_CONFIRM=true`）
  - 账本持久化：`memory/atp-autobuy-ledger.json`
- **DoD**:
  - [ ] 预算超支时拒绝下单
  - [ ] 账本格式与 Node.js 版互操作
  - [ ] 崩溃后重启能恢复未结算订单状态
- **依赖**: `atp/hub_client.py`, `atp/protocol.py`
- **测试对标**: `test/atpAutoBuyer.test.js`, `test/atpCliBuy.test.js`

#### P0.3.4 `evolver/atp/auto_deliver.py` — 自动商家交付
- **功能**: 自动认领 Hub 任务，执行并提交交付证明。
- **关键逻辑**:
  - 轮询 `/a2a/task/my`（每 60s）
  - 查找已认领且未交付的任务
  - 调用 gene/capsule 执行（复用 `gep/solidify.py`）
  - 提交交付证明（git diff、test output、日志）
  - 追踪账本防止重复提交：`memory/atp-autodeliver-ledger.json`
- **DoD**:
  - [ ] 交付证明包含可重现的验证命令
  - [ ] 同一任务不重复交付
  - [ ] 执行失败时标记为 `failed` 并附带错误日志
- **依赖**: `atp/hub_client.py`, `gep/solidify.py`
- **测试对标**: `test/atpAutoDeliver.test.js`, `test/atpTaskPickup.test.js`

#### P0.3.5 `evolver/atp/consumer_agent.py` — 消费者代理模板
- **功能**: 面向用户的消费者代理生命周期管理。
- **API**: `order_service`, `confirm_delivery`, `request_ai_judge`, `settle`, `dispute`, `check_order`, `get_policy`, `order_and_wait`
- **DoD**:
  - [ ] `order_and_wait` 阻塞直到订单 settle 或 timeout（最大 24h）
  - [ ] AI Judge 争议时自动提交证据包
- **依赖**: `atp/hub_client.py`

#### P0.3.6 `evolver/atp/merchant_agent.py` — 商家代理模板
- **功能**: 面向开发者的商家代理生命周期管理。
- **API**: `register_service`, `start_heartbeat`, `poll_orders`, `on_order_handler`, `submit_delivery`
- **DoD**:
  - [ ] 服务注册后 Heartbeat 上报可用状态
  - [ ] 订单到来时回调用户注册的 `on_order` 处理器
- **依赖**: `atp/hub_client.py`, `proxy/lifecycle/manager.py`

#### P0.3.7 `evolver/atp/atp_task_pickup.py` — 任务认领
- **功能**: 自动发现并认领高 ROI 任务。
- **DoD**:
  - [ ] ROI 评分：赏金金额 / 预估工作量
  - [ ] 能力匹配：只认领与本地基因匹配的任务
  - [ ] 并发限制：同时最多 3 个进行中的任务
- **测试对标**: `test/atpTaskPickup.test.js`

#### P0.3.8 `evolver/atp/atp_execute.py` — ATP 执行桥
- **功能**: 在 ATP 交付上下文中执行基因验证命令。
- **DoD**:
  - [ ] 复用 `gep/validator/sandbox_executor.py` 的安全模型
  - [ ] 输出格式化为标准交付证明
- **测试对标**: `test/atpExecute.test.js`

#### P0.3.9 `evolver/atp/heartbeat_signals_handler.py` — ATP 心跳信号处理
- **功能**: 将 Hub 下发的 ATP 相关信号转换为本地进化信号。
- **DoD**:
  - [ ] 新订单信号 → `atp_new_order`
  - [ ] 订单超时信号 → `atp_order_timeout`
  - [ ] 争议信号 → `atp_dispute_received`
- **测试对标**: `test/atpHeartbeatSignalsHandler.test.js`

#### P0.3.10 `evolver/atp/service_helper.py` — 服务发布辅助
- **功能**: 辅助用户将本地技能打包为 ATP 服务。
- **DoD**:
  - [ ] 从 `SKILL.md` 提取服务描述
  - [ ] 自动生成服务定价建议

#### P0.3.11 `evolver/atp/question_composer.py` — 赏金问题组合器
- **功能**: 将能力缺口组合为适合发布赏金的问题描述。
- **DoD**:
  - [ ] 输出格式符合 Hub 赏金 schema
  - [ ] 自动附加相关基因 ID 作为上下文

#### P0.3.12 `evolver/atp/cli.py` — ATP CLI 子命令完整实现
- **功能**: 实现缺失的 ATP 相关 CLI 命令。
- **需实现命令**:
  - `evolver atp enable/disable/status` — 启用/禁用 ATP 模式
  - `evolver atp orders` — 列出我的订单
  - `evolver atp tasks` — 列出可用任务
  - `evolver atp publish` — 发布服务
  - `evolver atp settle <order_id>` — 手动结算
  - `evolver atp dispute <order_id> --reason=...` — 发起争议
- **DoD**:
  - [ ] 所有命令参数与 Node.js 版一致
  - [ ] `evolver atp status` 显示当前模式、余额、进行中的订单数

#### P0.3.13 `evolver/atp/cli_autobuy_prompt.py` — 首次运行交互式同意提示
- **功能**: 首次启用 `auto_buyer` 时，向用户展示风险说明并请求确认。
- **DoD**:
  - [ ] 显示每日预算、每单上限、冷启动保护说明
  - [ ] 用户输入 `yes` 后生成 `~/.evomap/atp-consent`
  - [ ] 非交互式环境（CI）自动跳过并禁用 auto_buyer
- **测试对标**: `test/atpCliBuy.test.js`

---

### P0.4 IDE 适配器运行时 Hooks

**参考**: `evolver/src/adapters/` (8 文件 + 5 scripts)

> 当前 Python 版 `evolver/adapters/setup_hooks.py` 仅将静态配置文件写入 IDE 配置目录（如 `.cursor/rules.mdc`）。Node.js 版安装了完整的运行时生命周期 hooks，使 IDE 能在会话启动、信号检测、会话结束时与 evolver 交互。

#### P0.4.1 `evolver/adapters/hook_adapter.py` — 共享适配器逻辑
- **功能**: 所有 IDE 适配器的公共逻辑。
- **关键行为**:
  - **平台检测**: 自动检测 workspace 中使用的 IDE（Cursor、Claude Code、Codex、Kiro、OpenCode、VS Code Generic）
  - **JSON 合并**: 安全合并 hook 配置到现有 JSON 文件（保留用户原有设置）
  - **Markdown section 编辑**: 在 `AGENTS.md` 中插入/更新 `<!-- evolver-start -->...<!-- evolver-end -->` 标记区域
  - **符号链接安全**: 拒绝向符号链接目录写入（防止目录遍历）
  - **脚本复制/移除**: 将运行时脚本从 `evolver/adapters/scripts/` 复制到 IDE hooks 目录，卸载时清理
  - **标记区域清理**: 卸载时完整移除 evolver 注入的内容，不留残余
- **DoD**:
  - [ ] 支持同时安装多个 IDE 的 hooks
  - [ ] 重复安装是幂等的（不重复注入）
  - [ ] 卸载后 IDE 配置文件恢复原始状态
  - [ ] 符号链接攻击测试：拒绝写入 symlink 目录
- **依赖**: `gep/paths.py`
- **测试对标**: `test/adapters.test.js`, `test/adaptersSyntax.test.js`

#### P0.4.2 `evolver/adapters/scripts/session_start.py` — 会话启动注入
- **功能**: IDE 会话开始时，注入相关记忆和上下文。
- **执行时机**: IDE 启动或新会话创建时
- **关键行为**:
  - 读取 `memory_graph.jsonl`，按当前 workspace 和信号相关性过滤
  - 提取 top-5 相关记忆（按置信度和时间衰减排序）
  - 输出 JSON 到 stdout，供 IDE 消费（格式与 Node.js 版一致）
  - 支持 `--scope=global|workspace|session` 参数
- **输出格式**:
  ```json
  {
    "evolver_context": {
      "workspace_id": "...",
      "relevant_memories": [
        {"signal": "...", "outcome": "...", "score": 0.85, "ts": "..."}
      ],
      "personality_hint": "..."
    }
  }
  ```
- **DoD**:
  - [ ] 输出 JSON 通过 schema 验证
  - [ ] 无记忆时输出空数组，不报错
  - [ ] 执行时间 < 500ms（避免阻塞 IDE 启动）
- **测试对标**: `test/sessionStartScope.test.js`, `test/sessionFormat.test.js`

#### P0.4.3 `evolver/adapters/scripts/signal_detect.py` — 信号检测脚本
- **功能**: 在 IDE 工作流中检测进化信号（错误、测试失败、性能问题）。
- **触发方式**: IDE 文件保存时、终端输出变化时（取决于 IDE 能力）
- **检测模式**:
  - 扫描终端输出中的错误模式（复用 `gep/signals.py` 的 regex 层）
  - 检测文件保存后的测试失败（读取 `.evolver/test-output.jsonl`）
  - 性能瓶颈检测：监控文件大小突变、构建时间增长
- **输出**: 将检测到的信号写入 `memory/signals-detected.jsonl`
- **DoD**:
  - [ ] 检测延迟 < 1s（文件保存后）
  - [ ] 误报率 < 5%（通过历史数据校准）
  - [ ] 支持 4 种语言的错误模式（英/简中/繁中/日）
- **测试对标**: `test/signalDetect.test.js`

#### P0.4.4 `evolver/adapters/scripts/session_end.py` — 会话结束记录
- **功能**: IDE 会话结束时，记录会话统计到记忆图。
- **执行时机**: IDE 关闭或会话显式结束时
- **记录内容**:
  - git diff 统计（修改文件数、增删行数）
  - 会话持续时间
  - 检测到的信号列表
  - 用户显式反馈（如评分）
- **DoD**:
  - [ ] 成功写入 `memory_graph.jsonl`
  - [ ] git diff 命令失败时不阻塞（ graceful fallback）
- **测试对标**: `test/sessionEndHook.test.js`

#### P0.4.5 `evolver/adapters/scripts/task_recall.py` — 运行时任务回忆注入
- **功能**: 按用户提示（opt-in）回忆相关历史任务和解决方案。
- **触发方式**: 用户输入包含 `@evolver recall` 或类似关键词
- **行为**:
  - 解析用户当前编辑文件和光标位置
  - 查询 memory graph 中相似场景的处理记录
  - 返回最相关的 capsule 摘要
- **DoD**:
  - [ ] 召回准确率 > 70%（与 Node.js 版 benchmark 对齐）
- **测试对标**: `test/taskRecall.test.js`

#### P0.4.6 `evolver/adapters/scripts/runtime_paths.py` — 共享路径解析
- **功能**: 为所有运行时脚本提供统一的路径解析。
- **DoD**:
  - [ ] 支持从任何 cwd 正确找到 workspace root
  - [ ] 缓存路径结果，避免重复 git 遍历

#### P0.4.7 `evolver/adapters/scripts/memory_filtering.py` — 共享记忆过滤工具
- **功能**: 为运行时脚本提供记忆过滤和排序工具。
- **DoD**:
  - [ ] 按信号键、时间范围、置信度过滤
  - [ ] 支持时间衰减算法（指数衰减，半衰期 7 天）
- **测试对标**: `test/memoryFiltering.test.js`

#### P0.4.8 `evolver/adapters/cursor.py` — Cursor 完整适配
- **当前状态**: `setup_hooks.py` 中已部分实现静态配置写入。
- **需增强**:
  - 输出 `.cursor/hooks.json`（运行时 hook 注册）
  - 输出 `.cursor/hooks/evolver-session-start.js`（调用 `session_start.py`）
  - 输出 `.cursor/hooks/evolver-signal-detect.js`（调用 `signal_detect.py`）
  - 输出 `.cursor/hooks/evolver-session-end.js`（调用 `session_end.py`）
- **DoD**:
  - [ ] hooks.json 格式符合 Cursor 官方 schema
  - [ ] JS wrapper 正确调用 Python 脚本（使用 `python -m evolver.adapters.scripts.session_start`）

#### P0.4.9 `evolver/adapters/claude_code.py` — Claude Code 完整适配
- **需实现**: `.claude/settings.json` hook 注册 + `.claude/hooks/*.js` 脚本
- **DoD**: 与 Cursor 适配器同等标准

#### P0.4.10 `evolver/adapters/codex.py` — Codex 适配
- **需实现**: `.codex/hooks.json` + `.codex/hooks/*.js` + `.codex/config.toml` 切换
- **DoD**:
  - [ ] 支持 `config.toml` 中 `[evolver]` 区块的读写
  - [ ] AGENTS.md 注入支持 Codex 特殊标记
- **测试对标**: `test/adapters.test.js`

#### P0.4.11 `evolver/adapters/kiro.py` — Kiro 适配
- **需实现**: `.kiro/hooks/*.kiro.hook` + `.kiro/hooks/*.js` + `AGENTS.md` 注入
- **DoD**:
  - [ ] `.kiro.hook` 文件格式符合 Kiro 规范
- **测试对标**: `test/adapters.kiro.test.js`

#### P0.4.12 `evolver/adapters/opencode.py` — OpenCode 适配
- **需实现**: `.opencode/plugins/evolver.py` 服务器插件 + 事件 hooks + `verify` 命令
- **DoD**:
  - [ ] 插件实现 OpenCode 插件协议（`on_event`, `on_command`）
  - [ ] `verify` 命令触发本地 solidify 验证
- **测试对标**: `test/adapters.opencode.test.js`

---

## P1 — 核心功能（对"自进化引擎"声明至关重要）

### P1.1 运维与生命周期守护进程

**参考**: `evolver/src/ops/` (9 个文件)

#### P1.1.1 `evolver/ops/lifecycle.py` — 守护进程生命周期管理
- **功能**: 跨平台的进程启停、监控、自重启。
- **命令**: `start`, `stop`, `restart`, `status`, `tail_log`, `check_health`, `watch`
- **跨平台进程发现**:
  - **Windows**: WMI 查询 (`wmic process where "commandline like '%evolver%'%"`)
  - **Unix**: `ps` + `pgrep -f`
  - **通用**: PID 文件 `~/.evomap/instance.lock`
- **`watch` 模式**:
  - 监控循环：每 30s 检查进程存活
  - 时钟跳变检测：两次检查间隔 > 2min 视为系统睡眠唤醒，强制重启
  - 停滞自动重启：CPU 占用 < 1% 超过 10min 视为死锁，自动重启
- **日志轮转**: `~/.evomap/logs/evolver-{date}.log`，保留 7 天
- **DoD**:
  - [ ] Windows 下 `evolver start` 创建独立进程（非子进程），关闭终端不退出
  - [ ] `evolver status` 正确显示 PID、运行时间、当前策略、上次心跳时间
  - [ ] `evolver stop` 发送 SIGTERM，等待 30s 后 SIGKILL
  - [ ] 崩溃后 `evolver start` 自动恢复，续接上次进化状态
- **依赖**: `gep/instance_lock.py`
- **测试对标**: `test/ops.test.js`, `test/lifecycleForceUpdateTrigger.test.js`, `test/lifecycleHeartbeatLoopResilience.test.js`, `test/lifecycleRateLimit.test.js`

#### P1.1.2 `evolver/ops/health_check.py` — 系统健康检查
- **功能**: 检查本地系统资源，防止进化在恶劣环境下运行。
- **检查项**:
  - 磁盘用量（`shutil.disk_usage`，阈值 90%）
  - 内存用量（`psutil.virtual_memory`，阈值 95%）
  - 可选 secrets 存在性检查
  - 进程计数（Linux `/proc`，阈值 1000）
- **输出**: `HealthReport` Pydantic 模型，`status: healthy|warning|critical`
- **DoD**:
  - [ ] 磁盘满时返回 critical，阻止进化循环启动
  - [ ] 内存不足时建议 `evolver stop` 并发送通知
- **依赖**: `psutil`（新增可选依赖）
- **测试对标**: `test/healthCheck.test.js`

#### P1.1.3 `evolver/ops/self_repair.py` — Git 紧急修复
- **功能**: 进化过程中遇到 Git 异常时的自动修复。
- **修复场景**:
  - 检测进行中 rebase/merge → 自动 `git rebase --abort` / `git merge --abort`
  - 陈旧 `index.lock` → 删除（如果 PID 不存在）
  - 可选 hard reset 到 `origin/main`（需 `EVOLVER_SELF_REPAIR_HARD_RESET=1`）
  - 未跟踪文件过多 → 自动 `git clean -fd`（受保护路径外）
- **DoD**:
  - [ ] 修复前自动 stash 用户更改（`EVOLVER_ROLLBACK_MODE=stash`）
  - [ ] hard reset 需二次确认（非交互式环境默认禁用）
- **依赖**: `gep/git_ops.py`
- **测试对标**: `test/selfRepair.test.js`

#### P1.1.4 `evolver/ops/skills_monitor.py` — Skills 健康监控
- **功能**: 监控技能目录健康，自动修复常见问题。
- **检查项**:
  - `node_modules` 存在性（Node 技能）
  - `SKILL.md` 存在性和格式正确性
  - `package.json` / `pyproject.toml` 依赖完整性
  - `.venv` / `node_modules` 损坏检测
- **自动修复**:
  - 缺失 `node_modules` → 自动 `npm install`
  - 缺失 `SKILL.md` → 创建存根文件（带 TODO 模板）
  - Python 技能缺失 `.venv` → 自动 `uv sync` 或 `pip install -e .`
- **DoD**:
  - [ ] 修复前备份原文件（`.bak`）
  - [ ] 修复失败时记录 error 事件到 `events.jsonl`
- **测试对标**: `test/skillsMonitor.test.js`

#### P1.1.5 `evolver/ops/commentary.py` — 评论生成器
- **功能**: 为进化事件生成人类可读的中文/英文评论摘要。
- **DoD**:
  - [ ] 单次进化评论 < 140 字（适合通知）
  - [ ] 支持 `--verbose` 生成详细技术评论

#### P1.1.6 `evolver/ops/innovation.py` — 创新追踪
- **功能**: 追踪和评估创新尝试的成功率。
- **DoD**:
  - [ ] 记录每次 `innovate` 策略的产出
  - [ ] 计算创新 ROI（成功 capsule 数 / 尝试数）

#### P1.1.7 `evolver/ops/trigger.py` — 触发器工具
- **功能**: 外部触发进化循环（如 GitHub webhook、定时任务）。
- **DoD**:
  - [ ] 支持 HTTP POST 触发（`localhost:19820/trigger`）
  - [ ] 支持文件系统触发（`memory/.trigger` 文件存在时立即进化）

---

### P1.2 GEP 高级模块 — 自动蒸馏与评估

**参考**: `evolver/src/gep/` (混淆核心模块，需基于测试契约重构)

#### P1.2.1 `evolver/gep/auto_distill_conv.py` — 对话自动蒸馏
- **功能**: 将会话流（IDE 交互记录）自动转换为 GEP 资产。
- **输入**: `memory/session-{id}.jsonl`（对话记录）
- **输出**: 新的 Gene 或 Capsule
- **关键逻辑**:
  - 识别对话中的成功模式（用户确认、测试通过、无错误）
  - 提取系统提示词片段作为 gene 的 `signals_match`
  - 提取代码变更作为 capsule 的 `execution_trace`
  - 去重：与现有基因相似度 > 0.9 时合并而非新建
- **DoD**:
  - [ ] 从 10 轮成功对话中蒸馏出至少 1 个有效 gene
  - [ ] 蒸馏结果通过 `gep/schemas/gene.py` 验证
- **依赖**: `gep/distill.py`, `gep/asset_store.py`, `gep/content_hash.py`
- **测试对标**: `test/autoDistillConv.test.js`

#### P1.2.2 `evolver/gep/auto_distill_llm.py` — LLM 自动蒸馏
- **功能**: 调用 LLM 分析历史事件，生成新的 gene/capsule。
- **提示策略**:
  - 输入：最近 50 条 `events.jsonl` + 当前 gene pool
  - 输出：JSON 格式的 gene 建议列表
  - 约束：禁止生成与现有 gene `id` 冲突的建议
- **DoD**:
  - [ ] LLM 输出通过 JSON schema 验证
  - [ ] 失败时回退到 rule-based 蒸馏
- **依赖**: `gep/distill.py`, `proxy/server/routes.py`（用于 LLM 调用）

#### P1.2.3 `evolver/gep/candidate_eval.py` — 候选评估引擎
- **功能**: 评估突变候选与当前信号的匹配度。
- **评分维度**:
  - 信号匹配度（0-40 分）
  - 历史成功率（0-30 分）
  - 环境兼容性（0-20 分）
  - 复杂度惩罚（0-10 分，越简单越好）
- **DoD**:
  - [ ] 评分与 Node.js 版在同一测试用例上偏差 < 5%
- **测试对标**: `test/candidates.test.js`

#### P1.2.4 `evolver/gep/conversation_sniffer.py` — 对话嗅探器
- **功能**: 实时嗅探 IDE 会话中的进化信号。
- **DoD**:
  - [ ] 不阻塞 IDE 主线程（异步读取）
  - [ ] 支持增量读取大文件（> 10MB）

#### P1.2.5 `evolver/gep/skill2gep.py` — Skill 反向蒸馏
- **功能**: 将 `SKILL.md` + 执行轨迹 → Gene + Capsule。
- **DoD**:
  - [ ] 保留 SKILL.md 中的元数据（作者、版本、依赖）
  - [ ] 生成的 gene 自动关联到原 skill ID

#### P1.2.6 `evolver/gep/skill_distiller.py` — 正向技能蒸馏
- **功能**: 从 capsule 流中蒸馏出通用 skill。
- **DoD**:
  - [ ] 识别跨 capsule 的通用模式
  - [ ] 输出符合 `write-a-skill` SKILL.md 格式

#### P1.2.7 `evolver/gep/skill_publisher.py` — 技能发布器
- **功能**: 将本地 gene 打包为技能并发布到 Hub。
- **关键逻辑**:
  - 清理 gene ID 为 kebab-case 技能名
  - 派生标题和描述（从 gene summary）
  - 验证：无 secret 泄漏、无混淆文件路径
  - 发布到 Hub `/a2a/skill/publish`
- **DoD**:
  - [ ] 发布前通过 `gep/sanitize.py` 安全检查
  - [ ] 发布失败时本地保留草稿（`memory/skill-drafts/`）
- **测试对标**: `test/skillPublisher.test.js`

---

### P1.3 GEP 认知与记忆增强

#### P1.3.1 `evolver/gep/curriculum.py` — 课程学习
- **功能**: 结构化学习进度指导进化方向。
- **DoD**:
  - [ ] 定义 5 级课程（基础修复 → 性能优化 → 架构重构 → 创新探索 → 自主研究）
  - [ ] 当前课程级别根据成功率自动晋升
- **测试对标**: `test/curriculum.test.js`

#### P1.3.2 `evolver/gep/epigenetics.py` — 表观遗传层完整实现
- **当前状态**: `gep/selector.py` 中已有简化版 epigenetic 抑制（hard boost）。
- **需增强**:
  - 环境指纹级记录（platform/arch/python_version/依赖版本）
  - 软抑制（boost -0.1 ~ -0.3）vs 硬抑制（boost ≤ -0.3 全局禁用）
  - 抑制衰减：30 天后自动解除软抑制
  - 环境变化检测：当环境指纹变化时重置部分抑制记录
- **DoD**:
  - [ ] 同一 gene 在 Windows 失败不影响 Linux 评分
  - [ ] 硬抑制的 gene 在 drift 模式中也被跳过
- **依赖**: `gep/selector.py`
- **测试对标**: `test/selector.test.js`（epigenetic 相关用例）

#### P1.3.3 `evolver/gep/explore.py` — 探索引擎
- **功能**: 定向探索突变空间，避免局部最优。
- **策略**:
  - 随机探索：小概率尝试完全无关的 gene 类别
  - 边界探索：在已知成功 gene 的参数边界外尝试
  - 反事实探索：假设当前策略错误，尝试相反策略
- **DoD**:
  - [ ] 探索成功率追踪（成功探索 / 总探索）
  - [ ] 探索预算：每日最多 3 次深度探索
- **测试对标**: `test/explore.test.js`

#### P1.3.4 `evolver/gep/learning_signals.py` — 学习信号完整版
- **当前状态**: `evolve/pipeline/signals.py` 已实现基础信号提取。
- **需增强**:
  - 平台特定信号（Windows shell 不兼容、macOS 路径大小写）
  - 依赖冲突信号（`uv.lock` / `package-lock.json` 冲突）
  - 性能回归信号（构建时间增长 > 20%）
- **DoD**:
  - [ ] 新增 10+ 信号类型
  - [ ] 信号提取延迟 < 100ms（Layer 1 + 2）

#### P1.3.5 `evolver/gep/memory_graph_adapter.py` — 记忆图高级查询接口
- **功能**: 在 `memory_graph.py` 基础上提供高级查询。
- **API**:
  - `query_by_signal(signal_key, time_range, limit)`
  - `query_by_outcome(status, min_score)`
  - `get_success_trajectory(signal_key) -> list[Event]`（成功路径回溯）
  - `get_failure_pattern(signal_key) -> dict`（失败模式聚类）
- **DoD**:
  - [ ] 查询 1 年数据（~10k 条）< 500ms
  - [ ] 支持模糊匹配（Levenshtein 距离 < 3）
- **依赖**: `gep/memory_graph.py`

#### P1.3.6 `evolver/gep/recall_inject.py` — 回忆注入引擎
- **功能**: 将蒸馏记忆注入到 GEP prompt 中。
- **注入策略**:
  - 相关性阈值：> 0.7 才注入
  - Token 预算：注入内容不超过 prompt 的 20%
  - 时效性偏好：最近 7 天的记忆权重 ×2
- **DoD**:
  - [ ] 注入后 prompt 总长度 < `EVOLVER_PROMPT_MAX_CHARS`
  - [ ] 注入位置：在 `## Context` 区块后，`## Instructions` 前
- **测试对标**: `test/recallInject.test.js`

#### P1.3.7 `evolver/gep/recall_verifier.py` — 回忆验证器
- **功能**: 确保注入的记忆准确且相关。
- **验证项**:
  - 事实一致性：记忆内容与当前代码库状态不矛盾
  - 相关性评分：记忆与当前信号的余弦相似度
  - 时效性检查：超过 90 天的记忆标记为 `[stale]`
- **DoD**:
  - [ ] 不准确记忆被过滤，不进入 prompt
  - [ ] 准确率 > 85%
- **测试对标**: `test/recallVerifier.test.js`

#### P1.3.8 `evolver/gep/reflection.py` — 反思引擎
- **功能**: 固化后分析、教训提取、人格适应。
- **当前状态**: `ops/narrative.py` 中有简化反思日志。
- **需增强**:
  - 固化结果分析：成功/失败归因（信号匹配度、验证命令、环境差异）
  - 教训提取：将失败模式提取为 `anti_patterns` 写入 gene
  - 人格适应：根据成功率调整 personality 的 `risk_tolerance` 和 `exploration_rate`
- **DoD**:
  - [ ] 每次固化后生成 `reflection.jsonl` 记录
  - [ ] 人格参数调整幅度 ≤ 10%（防止剧烈波动）
- **依赖**: `gep/personality.py`, `gep/memory_graph.py`

---

### P1.4 GEP 策略与合规

#### P1.4.1 `evolver/gep/policy_check.py` — 策略执行引擎
- **功能**: 在 solidify 前执行全面的安全策略检查。
- **检查项**:
  - 爆炸半径上限：`blast_radius.files <= max_files`（默认 20）
  - 文件类型限制：禁止修改 `.env`, `secrets/`, `*.key`
  - Secret 泄漏检查：复用 `sanitize.py`，扫描 diff 中的高熵字符串
  - 混淆文件保护：禁止覆盖 `evolver/` 自身源码（防止自毁）
  - 回滚安全：验证 `git stash` 或 `git reset` 不会丢失用户未跟踪文件
  - 关键路径保护：`MEMORY.md`, `package.json`, `pyproject.toml`, `uv.lock`
- **DoD**:
  - [ ] 任何策略检查失败都阻止 solidify，并记录 `policy_violation` 事件
  - [ ] 策略检查时间 < 2s
- **依赖**: `gep/sanitize.py`, `gep/git_ops.py`
- **测试对标**: `test/policyCheck.test.js`, `test/solidifySecurity.test.js`

#### P1.4.2 `evolver/gep/feature_flags.py` — 三层特性标志
- **功能**: 支持 env → disk → default 三层覆盖的特性标志系统。
- **当前状态**: 特性标志硬编码在 `config.py` 中。
- **需实现**:
  - `disk_flags.json`: 本地持久化的特性开关
  - 优先级：`env` > `disk` > `default`
  - 支持动态热加载（无需重启进程）
  - 标志列表：`enable_llm_review`, `enable_auto_buyer`, `enable_validator`, `enable_recall_inject`, `enable_curriculum`, `enable_explore`
- **DoD**:
  - [ ] 特性标志变更后 10s 内生效
  - [ ] 未知标志警告但不报错

#### P1.4.3 `evolver/gep/idle_scheduler.py` — OMLS 风格空闲调度器
- **功能**: 检测用户不活动，动态调整进化强度。
- **调度策略**:
  - 用户活跃（最近 5min 有键盘/鼠标输入）→ `signal_only`（仅信号检测）
  - 用户空闲 5-30min → `light`（轻量进化，每 10min 一次）
  - 用户空闲 30min-2h → `normal`（标准进化）
  - 用户空闲 > 2h → `deep`（深度进化，允许长时间验证）
- **检测方式**:
  - 终端：检测 `memory/` 目录最近修改时间
  - IDE：检测 session 心跳时间
  - 显式：用户设置 `EVOLVER_IDLE_OVERRIDE=deep`
- **DoD**:
  - [ ] 不误判：编译/构建期间视为活跃
  - [ ] 深度进化前发送桌面通知（Windows toast / macOS notification / Linux notify-send）
- **测试对标**: `test/idleScheduler.test.js`

#### P1.4.4 `evolver/gep/local_state_awareness.py` — 本地状态感知完整版
- **当前状态**: 基础实现已存在，需增强。
- **需补充**:
  - 完整捕获：节点身份、环境配置、进化状态、记忆状态、技能状态、ATP 状态
  - 状态哈希：生成 `local_state_hash`，用于检测环境漂移
  - 状态注入：将状态摘要注入 GEP prompt 的 `## Local State` 区块
- **DoD**:
  - [ ] 状态摘要 < 500 字
  - [ ] 敏感字段（token、secret）脱敏处理

---

### P1.5 自动化运维与报告

#### P1.5.1 `evolver/gep/issue_reporter.py` — 自动 GitHub Issue 报告器
- **功能**: 对反复出现的错误自动创建 GitHub Issue。
- **流程**:
  - 检测到同一信号 3 次重复失败 → 触发 issue 报告
  - 搜索现有 issues（GitHub API + 本地缓存）→ 避免重复
  - 创建新 issue：标题（信号摘要）、正文（脱敏日志、环境指纹、相关 gene ID）
  - 冷却期：同一信号 7 天内不重复报告
- **DoD**:
  - [ ] 脱敏：所有路径中的用户名替换为 `<USER>`，token 替换为 `<REDACTED>`
  - [ ] 无 `GITHUB_TOKEN` 时静默跳过，不报错
  - [ ] Issue 标签：`evolver-auto`, `bug` 或 `enhancement`
- **依赖**: `gep/env_fingerprint.py`, `gep/sanitize.py`
- **测试对标**: `test/issueReporter.test.js`

#### P1.5.2 `evolver/gep/self_pr.py` — 自 PR
- **功能**: 为高置信度突变自动创建 GitHub Pull Request。
- **触发条件**:
  - solidify 评分 >= `EVOLVER_SELF_PR_MIN_SCORE`（默认 0.85）
  - 无策略违反
  - 无 secret 泄漏
  - 冷却期：同一分支 24h 内不重复提 PR
  - diff 去重：与已打开 PR 的 diff 相似度 < 0.9
- **流程**:
  - 创建分支：`evolver-auto/{timestamp}-{gene-id}`
  - 提交：commit message 来自 gene summary
  - 推送：`git push origin`
  - 创建 PR：`gh pr create` 或 GitHub API
  - 注册到 `open_pr_registry.json`
- **DoD**:
  - [ ] PR 描述包含：动机、变更摘要、验证命令、环境指纹
  - [ ] 失败时回滚分支创建（不污染远程）
  - [ ] 无 `gh` CLI 时回退到 GitHub API（需 `GITHUB_TOKEN`）
- **依赖**: `gep/policy_check.py`, `gep/git_ops.py`
- **测试对标**: `test/selfPR.test.js`

#### P1.5.3 `evolver/gep/open_pr_registry.py` — 开放 PR 注册表
- **功能**: 追踪待处理 PR，防止重复提交。
- **DoD**:
  - [ ] 自动检测 PR 状态变化（merged/closed）
  - [ ] merged PR 自动归档为 capsule

#### P1.5.4 `evolver/gep/question_generator.py` — 主动问题生成器
- **功能**: 为 Hub 赏金系统生成高质量问题。
- **约束**:
  - 速率限制：每日最多 3 个问题
  - 紧急路径绕过：CRITICAL 信号可无视速率限制
  - 基础设施错误过滤：不将网络/磁盘问题生成赏金
- **DoD**:
  - [ ] 问题包含：背景、复现步骤、预期结果、赏金金额
  - [ ] 自动生成测试用例草案

#### P1.5.5 `evolver/gep/task_receiver.py` — 任务接收器
- **功能**: 从 Hub 拉取外部任务，自动认领并注入为本地进化信号。
- **流程**:
  - 轮询 `/a2a/task/open`
  - ROI 评分：赏金 / 预估工时
  - 能力匹配：任务信号与本地 gene pool 的匹配度
  - 自动认领：ROI > 1.5 且匹配度 > 0.6 时自动 claim
  - 注入为 `external_task` 信号，进入正常进化流水线
- **DoD**:
  - [ ] 认领前检查当前负载（最多 3 个并行外部任务）
  - [ ] 任务超时前 1h 自动提醒
- **依赖**: `gep/a2a_protocol.py`, `proxy/sync/inbound.py`

#### P1.5.6 `evolver/gep/llm_review.py` — LLM diff 审查门
- **功能**: solidify 前增加 LLM 审查关卡。
- **流程**:
  - 构建审查提示：git diff + gene 意图 + 安全约束
  - 调用 LLM（通过 Proxy `/v1/messages`）
  - 返回：`approved` (bool), `confidence` (0-1), `concerns` (list[str])
  - `approved=false` 或 `confidence < 0.7` → 阻止 solidify，进入 review 模式
- **DoD**:
  - [ ] 审查延迟 < 10s（diff < 100 行）
  - [ ] 审查结果持久化到 `memory/llm-reviews.jsonl`
- **依赖**: `proxy/server/routes.py`（LLM 调用）

---

## P2 — 增强体验（影响可用性和平台集成）

### P2.1 WebUI 高级功能

**参考**: `evolver/src/webui/` (24 个文件)

> 当前 Python 版 WebUI 仅有一个自包含的暗色 HTML 仪表盘（`dashboard.py`），无交互能力。Node.js 版有完整的 observer + client JS 子系统，支持实时图表、多语言、资产浏览。

#### P2.1.1 `evolver/webui/observer/` — 观察者子系统（10 模块）
- **功能**: 将本地状态转换为 WebUI 可消费的数据结构。
- **需实现模块**:
  - `observer/assets.py` — 资产（genes/capsules）序列化，支持过滤和分页
  - `observer/interactions.py` — 交互记录格式化
  - `observer/jsonl.py` — JSONL 文件流式解析（支持 100MB+ 文件）
  - `observer/paths.py` — 路径脱敏（隐藏绝对路径中的用户名）
  - `observer/personality.py` — 人格状态可视化数据
  - `observer/pipeline_events.py` — 流水线事件时间线
  - `observer/redact.py` — 敏感信息脱敏（secret、token、密码）
  - `observer/runs.py` — 进化运行历史统计
  - `observer/safety.py` — 安全事件聚合
  - `observer/skills.py` — 技能目录状态
  - `observer/status.py` — 系统健康状态汇总
- **DoD**:
  - [ ] 每个 observer 模块有独立单元测试
  - [ ] 大数据量（10k genes）下响应 < 1s
  - [ ] 所有路径输出使用相对路径或脱敏路径

#### P2.1.2 `evolver/webui/client/` — 客户端 JS 模块
- **功能**: 浏览器端交互逻辑，替代当前的纯静态 HTML。
- **需实现模块**:
  - `client/index_html.py` — 动态 HTML 模板（注入初始状态）
  - `client/styles_css.py` — 暗色主题 CSS（支持响应式布局）
  - `client/static.py` — 静态资源服务（favicon、字体）
  - `client/client_js/assets.js` — 资产表格：排序、搜索、分页、详情弹窗
  - `client/client_js/bootstrap.js` — 应用初始化、路由、错误边界
  - `client/client_js/common.js` — 共享工具（日期格式化、debounce、 throttle）
  - `client/client_js/i18n.js` — 多语言支持（英/简中/繁中/日/韩）
  - `client/client_js/interactions.js` — 交互时间线：折叠/展开、筛选
  - `client/client_js/overview.js` — 概览仪表盘：统计卡片、最近活动、成功率趋势
  - `client/client_js/personality.js` — 人格雷达图（echarts）
  - `client/client_js/pipelines.js` — 流水线实时可视化（阶段进度、耗时）
- **技术栈**: 纯 Vanilla JS（无 React/Vue 依赖），echarts 图表（内嵌 minified）
- **DoD**:
  - [ ] 首屏加载 < 2s（localhost）
  - [ ] 实时更新：SSE 连接断开后 3s 内自动重连
  - [ ] 移动端可用（最小宽度 375px）

#### P2.1.3 `evolver/webui/server/routes.py` — 完整 REST API
- **功能**: 为 WebUI client 提供数据接口。
- **路由表**:
  - `GET /api/status` — 系统状态
  - `GET /api/assets` — 资产列表（支持 `?type=gene|capsule&page=&limit=&q=`）
  - `GET /api/assets/{id}` — 资产详情
  - `GET /api/candidates` — 候选基因
  - `GET /api/calls` — 资产调用日志
  - `GET /api/lineage` — 基因血统（gene → capsule → event 链路）
  - `GET /api/interactions` — 交互记录
  - `GET /api/personality` — 人格状态
  - `GET /api/memory-graph` — 记忆图查询
  - `GET /api/skills` — 技能目录
  - `GET /api/logs` — 日志流（SSE）
  - `GET /api/safety` — 安全事件
  - `GET /api/runs` — 运行历史
- **DoD**:
  - [ ] 所有路由支持 `Accept: application/json`
  - [ ] 错误统一返回 `{error: str, code: str}` 格式

---

### P2.2 Hub 交互增强

#### P2.2.1 `evolver/gep/hub_fetch.py` — Hub 获取客户端
- **功能**: 带重试、缓存、熔断器的 Hub 数据获取。
- **DoD**:
  - [ ] 缓存 TTL：5min（可配置）
  - [ ] 熔断器：连续 5 次失败开启，30s 后半开试探

#### P2.2.2 `evolver/gep/hub_review.py` — Hub 审查引擎
- **功能**: 获取并审查 Hub 上的资产。
- **DoD**:
  - [ ] 支持批量审查（一次最多 10 个资产）
  - [ ] 审查结果本地缓存，避免重复下载

#### P2.2.3 `evolver/gep/hub_search.py` — Hub 语义 + 信号搜索
- **功能**: 结合语义相似度和信号匹配度搜索 Hub 资产。
- **DoD**:
  - [ ] 支持本地信号作为搜索上下文
  - [ ] 结果排序：语义相似度 × 信号匹配度 × Hub 评分

#### P2.2.4 `evolver/gep/hub_verify.py` — Hub 资产验证
- **功能**: 验证从 Hub 下载的资产的完整性和安全性。
- **DoD**:
  - [ ] SHA-256 校验和验证
  - [ ] 签名验证（如果资产已签名）

#### P2.2.5 `evolver/gep/analyzer.py` — 故障分析器
- **功能**: 解析 `MEMORY.md` 中的故障模式，生成结构化诊断。
- **DoD**:
  - [ ] 支持 20+ 常见故障模式识别
  - [ ] 输出 `AnalyzerReport` Pydantic 模型

---

### P2.3 基础设施与工具

#### P2.3.1 `evolver/gep/portable.py` — 便携 `.gepx` 归档
- **功能**: 导出当前 workspace 的所有 GEP 资产为单个 `.gepx` 文件。
- **格式**: gzip-tar，包含：
  - `genes.json` + `genes.jsonl`
  - `capsules.json` + `capsules.jsonl`
  - `events.jsonl`（最近 1000 条）
  - `memory_graph.jsonl`（最近 1000 条）
  - `manifest.json`（元数据、版本、SHA-256 校验和）
- **DoD**:
  - [ ] 导出命令：`evolver export --output=backup.gepx`
  - [ ] 导入命令：`evolver import backup.gepx`（合并策略：timestamp 优先）
  - [ ] 校验和验证失败时拒绝导入

#### P2.3.2 `evolver/gep/privacy_client.py` — 隐私计算 API 客户端
- **功能**: 与 EvoMap 隐私计算服务交互。
- **API**:
  - 加密 blob 上传（AES-256-GCM + RSA 混合加密）
  - 密封工具注册/执行
  - 状态轮询、结果检索（本地解密）
- **DoD**:
  - [ ] 端到端加密：服务端无法解密用户数据

#### P2.3.3 `evolver/gep/workspace_keychain.py` — 工作区密钥链
- **功能**: 工作区范围内的 secrets 安全存储。
- **实现**: 使用 `keyring` 库（Windows Credential Manager / macOS Keychain / Linux secret-service）
- **DoD**:
  - [ ] 支持设置/获取/删除/列出 secrets
  - [ ] fallback 到 `~/.evomap/keychain.json`（AES-256-GCM 加密）

#### P2.3.4 `evolver/gep/token_savings.py` — Token 节省追踪器
- **功能**: 估算并报告进化带来的 token/成本节省。
- **算法**:
  - 基准：无进化时解决问题的平均 token 消耗（历史均值）
  - 实际：有进化时的 token 消耗
  - 节省 = 基准 - 实际
- **DoD**:
  - [ ] 每月生成 `token-savings-report.md`
  - [ ] 支持 USD 成本估算（按模型定价）

#### P2.3.5 `evolver/gep/device_id.py` — 设备 ID 管理
- **功能**: 生成稳定且匿名的设备标识符。
- **DoD**:
  - [ ] 基于硬件特征哈希，同一设备重启后 ID 不变
  - [ ] 不包含任何可识别个人信息

#### P2.3.6 `evolver/gep/directory_client.py` — 目录客户端
- **功能**: 与 EvoMap 目录服务交互（节点发现、服务注册）。
- **DoD**:
  - [ ] 支持注册本地服务能力
  - [ ] 支持查询附近节点（用于 P2P 协作）

#### P2.3.7 `evolver/gep/mailbox_transport.py` — 邮箱传输层
- **功能**: 通过本地代理发送/接收/列出消息，保持代理存活。
- **DoD**:
  - [ ] 代理未启动时自动启动（`evolver proxy`）
  - [ ] A2A 协议注册：节点上线时向 Hub 注册 mailbox endpoint

---

### P2.4 强制更新

#### P2.4.1 `evolver/force_update.py` — 强制更新引擎
- **功能**: Hub 触发版本过期时，自动更新 evolver 本身。
- **更新渠道**:
  - Channel 1: GitHub Release（通过 `degit` 或 `git clone`）
  - Channel 2: 手动 URL（企业内网部署）
- **安全机制**:
  - 语义化版本解析/比较：`1.89.2` < `1.90.0` < `2.0.0`
  - 原子文件替换：下载到临时目录，验证校验和后 `os.replace`
  - 并发保护：文件锁防止多进程同时更新
  - Keep List：`memory/`, `.env`, `skills/` 目录不被覆盖
- **DoD**:
  - [ ] 更新失败时自动回滚到旧版本
  - [ ] 更新前自动备份当前版本（`~/.evomap/backups/`）
  - [ ] 更新后自动验证：`evolver --version` 返回新版本
  - [ ] 非交互式环境默认禁用自动更新（需 `EVOLVER_FORCE_UPDATE=1`）
- **依赖**: `ops/lifecycle.py`（更新后重启守护进程）
- **测试对标**: `test/forceUpdateConcurrencyGuard.test.js`, `test/forceUpdateHeartbeat.test.js`, `test/forceUpdateIdempotent.test.js`, `test/forceUpdateKeepList.test.js`, `test/forceUpdateLastUpdateReport.test.js`

---

## P3 — 锦上添花（不影响核心功能，但提升完整度）

### P3.1 测试覆盖率追赶

> Node.js 原版有 **~160 个测试文件**。Python 移植目前有 **~41 个测试文件**。需要为每个 P0/P1 模块补充测试，目标 **120+ 测试文件**。

#### P3.1.1 ATP 测试套件（10+ 文件）
- [ ] `tests/test_atp_auto_buyer.py` — 预算控制、去重、同意流程
- [ ] `tests/test_atp_auto_deliver.py` — 交付证明、重复提交防护
- [ ] `tests/test_atp_consumer_agent.py` — 生命周期、争议流程
- [ ] `tests/test_atp_merchant_agent.py` — 服务注册、订单处理
- [ ] `tests/test_atp_hub_client.py` — API 调用、重试、错误处理
- [ ] `tests/test_atp_protocol.py` — 枚举一致性、模型验证
- [ ] `tests/test_atp_task_pickup.py` — ROI 评分、能力匹配
- [ ] `tests/test_atp_execute.py` — 执行桥、安全沙箱
- [ ] `tests/test_atp_heartbeat_signals.py` — 信号转换
- [ ] `tests/test_atp_cli.py` — 子命令参数、输出格式
- **测试对标**: `test/atpAutoBuyer.test.js`, `test/atpAutoDeliver.test.js`, `test/atpCliBuy.test.js`, `test/atpExecute.test.js`, `test/atpHeartbeatSignalsHandler.test.js`, `test/atpProxyRouting.test.js`, `test/atpTaskPickup.test.js`, `test/atp-default.test.js`

#### P3.1.2 Proxy 测试套件（15+ 文件）
- [ ] `tests/test_proxy_lifecycle.py` — hello、心跳、reauth、唤醒恢复
- [ ] `tests/test_proxy_mailbox.py` — send/poll/ack/list、并发、崩溃恢复
- [ ] `tests/test_proxy_sync.py` — outbound/inbound、离线模式、批量发送
- [ ] `tests/test_proxy_server_routes.py` — 所有 REST 路由、认证、参数验证
- [ ] `tests/test_proxy_router_anthropic.py` — Anthropic 透传、流式响应
- [ ] `tests/test_proxy_router_bedrock.py` — Bedrock 转换、SigV4、event-stream
- [ ] `tests/test_proxy_router_model.py` — 模型路由、降级保护
- [ ] `tests/test_proxy_router_features.py` — 特性标志热切换
- [ ] `tests/test_proxy_extensions_dm.py` — DM 处理
- [ ] `tests/test_proxy_extensions_session.py` — 会话管理
- [ ] `tests/test_proxy_extensions_skill.py` — 技能更新
- [ ] `tests/test_proxy_extensions_trace.py` — 追踪控制
- [ ] `tests/test_proxy_task_monitor.py` — 任务监控、超时预警
- [ ] `tests/test_proxy_settings.py` — 设置持久化
- **测试对标**: `test/proxyAnthropic.test.js`, `test/proxyAssetSearchPlan.test.js`, `test/proxyBedrock.test.js`, `test/proxyServer.test.js`, `test/proxySettings.test.js`, `test/proxyStreaming.test.js`, `test/proxyTokenReuse.test.js`, `test/syncEngineLoopResilience.test.js`, `test/mailboxStore.test.js`, `test/taskMonitor.test.js`, `test/routerCanonicalizeBedrock.test.js`, `test/routerDegenerateTiers.test.js`, `test/routerFeatureFlag.test.js`, `test/routerFeatures.test.js`, `test/routerNoDowngrade.test.js`

#### P3.1.3 适配器测试套件（8+ 文件）
- [ ] `tests/test_adapters_hook.py` — 平台检测、JSON 合并、符号链接安全
- [ ] `tests/test_adapters_cursor.py` — 配置文件格式、运行时脚本
- [ ] `tests/test_adapters_claude.py` — 同上
- [ ] `tests/test_adapters_codex.py` — config.toml 切换
- [ ] `tests/test_adapters_kiro.py` — .kiro.hook 格式
- [ ] `tests/test_adapters_opencode.py` — 插件协议、verify 命令
- [ ] `tests/test_adapters_session_start.py` — 记忆注入、scope 过滤
- [ ] `tests/test_adapters_signal_detect.py` — 信号检测、多语言
- [ ] `tests/test_adapters_session_end.py` — git diff 统计、记忆写入
- [ ] `tests/test_adapters_memory_filtering.py` — 过滤、排序、衰减
- **测试对标**: `test/adapters.test.js`, `test/adapters.kiro.test.js`, `test/adapters.opencode.test.js`, `test/adaptersSyntax.test.js`, `test/sessionEndHook.test.js`, `test/sessionFormat.test.js`, `test/sessionStartScope.test.js`, `test/signalDetect.test.js`, `test/memoryFiltering.test.js`

#### P3.1.4 Ops 测试套件（6+ 文件）
- [ ] `tests/test_ops_lifecycle.py` — 跨平台进程管理、watch 模式、时钟跳变
- [ ] `tests/test_ops_health_check.py` — 磁盘/内存/进程检查
- [ ] `tests/test_ops_self_repair.py` — rebase/merge 中止、index.lock 清理
- [ ] `tests/test_ops_skills_monitor.py` — 依赖修复、SKILL.md 存根
- [ ] `tests/test_ops_commentary.py` — 评论生成、长度限制
- [ ] `tests/test_ops_innovation.py` — 创新 ROI 追踪
- **测试对标**: `test/ops.test.js`, `test/lifecycleForceUpdateTrigger.test.js`, `test/lifecycleHeartbeatLoopResilience.test.js`, `test/lifecycleLastUpdateAck.test.js`, `test/lifecycleNodeIdLegacyFallback.test.js`, `test/lifecycleNodeIdUnification.test.js`, `test/lifecycleRateLimit.test.js`, `test/lifecycleStaleNodeSecret.test.js`, `test/heartbeatResilienceRound*.test.js`, `test/loadBackoff.test.js`

#### P3.1.5 GEP 高级模块测试（20+ 文件）
- [ ] `tests/test_gep_auto_distill_conv.py`
- [ ] `tests/test_gep_auto_distill_llm.py`
- [ ] `tests/test_gep_candidate_eval.py`
- [ ] `tests/test_gep_curriculum.py`
- [ ] `tests/test_gep_epigenetics.py`
- [ ] `tests/test_gep_explore.py`
- [ ] `tests/test_gep_recall_inject.py`
- [ ] `tests/test_gep_recall_verifier.py`
- [ ] `tests/test_gep_reflection.py`
- [ ] `tests/test_gep_policy_check.py`
- [ ] `tests/test_gep_feature_flags.py`
- [ ] `tests/test_gep_idle_scheduler.py`
- [ ] `tests/test_gep_local_state.py`
- [ ] `tests/test_gep_issue_reporter.py`
- [ ] `tests/test_gep_self_pr.py`
- [ ] `tests/test_gep_open_pr_registry.py`
- [ ] `tests/test_gep_task_receiver.py`
- [ ] `tests/test_gep_llm_review.py`
- [ ] `tests/test_gep_validator.py`
- [ ] `tests/test_gep_validator_sandbox.py`

#### P3.1.6 WebUI 测试（5+ 文件）
- [ ] `tests/test_webui_observer.py`
- [ ] `tests/test_webui_client.py`
- [ ] `tests/test_webui_api.py`
- [ ] `tests/test_webui_sse.py`
- [ ] `tests/test_webui_websocket.py`

#### P3.1.7 性能与稳定性测试（4+ 文件）
- [ ] `tests/test_bench_pipeline.py` — 核心流水线性能基准
- [ ] `tests/test_cycle_hard_timeout.py` — 循环硬超时保护
- [ ] `tests/test_cycle_progress_file.py` — 进度文件原子写入
- [ ] `tests/test_rollback_safety.py` — 回滚安全（stash/reset/none）
- **测试对标**: `test/bench.test.js`, `test/cycleHardTimeout.test.js`, `test/cycleProgressFile.test.js`, `test/rollbackSafety.test.js`

---

### P3.2 文档与国际化

#### P3.2.1 英文 README 完善
- **当前状态**: 简短 README（~50 行）。
- **目标**: 完整 README（~500 行），包含：
  - 项目简介与架构图
  - 安装指南（`uv pip install` / `pip install`）
  - 快速开始（`evolver run`, `evolver --loop`）
  - CLI 命令参考
  - 环境变量完整列表
  - 配置文件示例
  - 故障排除
  - 贡献指南链接
- **DoD**: 与 Node.js 版 `README.md` 信息等价

#### P3.2.2 日文 README (`README.ja-JP.md`)
- **DoD**: 完整翻译，术语一致

#### P3.2.3 韩文 README (`README.ko-KR.md`)
- **DoD**: 完整翻译，术语一致

#### P3.2.4 中文 README (`README.zh-CN.md`)
- **DoD**: 完整翻译，术语一致

#### P3.2.5 SKILL.md
- **参考**: `evolver/SKILL.md`（8750 字，详细描述 Proxy mailbox API）
- **DoD**:
  - [ ] 描述 evolver 作为 Skill 的使用方式
  - [ ] 包含 Proxy API 完整参考
  - [ ] 包含 ATP 快速入门

#### P3.2.6 CONTRIBUTING.md
- **DoD**:
  - [ ] 开发环境搭建（`uv sync`, `pytest`）
  - [ ] 代码风格（`ruff`, `mypy`）
  - [ ] 提交规范
  - [ ] 测试要求

---

### P3.3 脚本与工具

> Node.js 版 `scripts/` 目录有 17 个工具脚本。Python 版 `scripts/` 目录为空。

#### P3.3.1 `scripts/a2a_export.py` — A2A 资产导出
- **功能**: 将本地 GEP 资产导出为 A2A 兼容格式。
- **DoD**: 输出通过 Hub `asset/validate` 验证

#### P3.3.2 `scripts/a2a_ingest.py` — A2A 资产导入
- **功能**: 从 A2A 格式导入资产到本地。
- **DoD**: 支持合并和覆盖两种模式

#### P3.3.3 `scripts/a2a_promote.py` — A2A 资产晋升
- **功能**: 将候选 gene 晋升为正式 gene。
- **DoD**: 自动运行 validation 命令验证

#### P3.3.4 `scripts/analyze_by_skill.py` — 按技能分析
- **功能**: 分析特定技能的进化效果。

#### P3.3.5 `scripts/build_binaries.py` — 二进制构建
- **功能**: 使用 `PyInstaller` 或 `nuitka` 构建独立可执行文件。
- **DoD**: Windows (.exe) / macOS / Linux 三平台

#### P3.3.6 `scripts/check_changelog.py` — 变更日志检查
- **功能**: 检查 `CHANGELOG.md` 格式和版本号一致性。

#### P3.3.7 `scripts/extract_log.py` — 日志提取
- **功能**: 从 `events.jsonl` 提取特定时间范围或信号类型的日志。

#### P3.3.8 `scripts/generate_history.py` — 历史生成
- **功能**: 生成进化历史报告（Markdown 格式）。

#### P3.3.9 `scripts/gep_append_event.py` — GEP 事件追加
- **功能**: CLI 工具手动追加事件到 `events.jsonl`。

#### P3.3.10 `scripts/gep_personality_report.py` — 人格报告
- **功能**: 生成人格状态可视化报告（HTML）。

#### P3.3.11 `scripts/human_report.py` — 人工可读报告
- **功能**: 将 `events.jsonl` 转换为人类可读的 Markdown 报告。

#### P3.3.12 `scripts/recall_verify_report.py` — 回忆验证报告
- **功能**: 分析回忆注入的准确率和覆盖率。

#### P3.3.13 `scripts/recover_loop.py` — 循环恢复
- **功能**: 守护进程崩溃后恢复进化状态。

#### P3.3.14 `scripts/seed_merchants.py` — 商家种子
- **功能**: 为 ATP 市场预置种子商家数据。

#### P3.3.15 `scripts/suggest_version.py` — 版本建议
- **功能**: 根据变更内容建议语义化版本号。

#### P3.3.16 `scripts/validate_modules.py` — 模块验证
- **功能**: 验证所有模块的导入和基本功能。

#### P3.3.17 `scripts/validate_suite.py` — 验证套件
- **功能**: 运行完整的验证测试套件（比 `pytest` 更全面的集成测试）。

---

### P3.4 性能与工程化

#### P3.4.1 核心流水线性能基准
- **目标**: 单次进化循环（不含 LLM 调用）< 5s（在 1000 gene / 1000 capsule 的数据集上）
- **方法**: `pytest-benchmark` 基准测试
- **对标**: `test/bench.test.js`

#### P3.4.2 循环模式硬超时保护
- **功能**: 防止单次循环无限挂起。
- **实现**: `asyncio.wait_for(ctx.cycle_task, timeout=config.cycle_timeout_ms)`
- **超时后**: 记录 `cycle_timeout` 事件，优雅保存状态，进入下一次循环
- **对标**: `test/cycleHardTimeout.test.js`

#### P3.4.3 循环进度文件原子写入
- **功能**: 守护进程崩溃后能从上次进度恢复。
- **实现**: `cycle_progress.json` 原子写入（temp + rename）
- **内容**: `{cycle_number, last_phase, last_successful_gene, timestamp, pid}`
- **对标**: `test/cycleProgressFile.test.js`

#### P3.4.4 回滚安全测试强化
- **场景**:
  - stash 模式下用户并行创建的文件不被误删（mtime 守卫）
  - hard 模式下 `CRITICAL_PROTECTED_FILES` 不被覆盖
  - none 模式下明确警告用户风险
- **对标**: `test/rollbackSafety.test.js`

#### P3.4.5 内存泄漏检测
- **目标**: 守护进程运行 24h，内存增长 < 50MB
- **方法**: `tracemalloc` 定期快照，对比 top 10 增长源

---

## 实施路线图建议

### Phase 1: 基础设施打底（预计 3-4 周）
**目标**: 让 Python 版能作为守护进程稳定运行，IDE 能感知进化。

1. **Week 1**: `ops/lifecycle.py` + `ops/health_check.py` + `ops/self_repair.py`
   - 产出: `evolver start/stop/status` 跨平台可用
2. **Week 2**: `proxy/lifecycle/manager.py` + `proxy/mailbox/store.py` + `proxy/server/routes.py`（核心路由）
   - 产出: Proxy 能独立存活，支持 mailbox API
3. **Week 3**: `proxy/sync/engine.py` + `proxy/sync/inbound.py` + `proxy/sync/outbound.py`
   - 产出: 离线模式可用，消息不丢失
4. **Week 4**: `adapters/hook_adapter.py` + 运行时 scripts + Cursor/Claude Code 完整适配
   - 产出: IDE 会话启动/结束/信号检测可用

### Phase 2: 商业闭环（预计 4-5 周）
**目标**: ATP 市场可用，支持自动买卖。

5. **Week 5-6**: `atp/protocol.py` + `atp/hub_client.py` + `atp/cli.py`
   - 产出: ATP CLI 子命令完整
6. **Week 7**: `atp/auto_buyer.py` + `atp/auto_deliver.py`
   - 产出: 自动消费和交付可用
7. **Week 8**: `atp/consumer_agent.py` + `atp/merchant_agent.py` + `atp/atp_task_pickup.py`
   - 产出: 商家/消费者代理模板可用
8. **Week 9**: ATP 集成测试 + 安全审计
   - 产出: 10+ ATP 测试文件全部通过

### Phase 3: 高级 GEP（预计 6-8 周）
**目标**: 自进化引擎的"智能"部分完整。

9. **Week 10-11**: `gep/policy_check.py` + `gep/feature_flags.py` + `gep/idle_scheduler.py` + `gep/local_state_awareness.py`
   - 产出: 策略合规系统可用
10. **Week 12-13**: `gep/auto_distill_conv.py` + `gep/auto_distill_llm.py` + `gep/skill2gep.py` + `gep/skill_distiller.py`
    - 产出: 自动蒸馏可用
11. **Week 14-15**: `gep/curriculum.py` + `gep/explore.py` + `gep/epigenetics.py`（完整版）
    - 产出: 课程学习和探索引擎可用
12. **Week 16-17**: `gep/recall_inject.py` + `gep/recall_verifier.py` + `gep/reflection.py`（完整版）
    - 产出: 记忆注入和反思可用

### Phase 4: 自动化（预计 4-5 周）
**目标**: 减少人工干预，实现自主运维。

13. **Week 18-19**: `gep/issue_reporter.py` + `gep/self_pr.py` + `gep/open_pr_registry.py`
    - 产出: 自动 Issue 报告和 PR 创建可用
14. **Week 20**: `gep/task_receiver.py` + `gep/question_generator.py` + `gep/llm_review.py`
    - 产出: 任务接收和审查门可用
15. **Week 21-22**: `gep/validator/`（完整实现）
    - 产出: 验证者模式可用，可参与去中心化网络

### Phase 5: 体验增强（预计 4-5 周）
**目标**: WebUI、Hub 增强、工具链完善。

16. **Week 23-24**: `webui/observer/` + `webui/client/` + `webui/server/routes.py`
    - 产出: 交互式 WebUI 可用
17. **Week 25**: `gep/hub_fetch.py` + `gep/hub_search.py` + `gep/hub_verify.py` + `gep/analyzer.py`
    - 产出: Hub 交互增强
18. **Week 26**: `gep/portable.py` + `gep/privacy_client.py` + `force_update.py`
    - 产出: 便携导出、隐私计算、强制更新

### Phase 6: 打磨（持续）
**目标**: 测试覆盖、文档、性能优化。

19. **Week 27-30**: 补充全部测试（目标 120+ 测试文件）
20. **Week 31**: 文档完善（README i18n、SKILL.md、CONTRIBUTING.md）
21. **Week 32**: 性能基准测试与优化
22. **持续**: 脚本工具完善、社区反馈迭代

---

## 风险与规避策略

| 风险 | 影响 | 规避策略 |
|---|---|---|
| Node.js 核心模块混淆，测试契约提取困难 | P1.2/P1.3 延迟 | 优先实现有明文测试的模块；对完全混淆的模块采用"接口先行、内部迭代"策略 |
| ATP/Proxy 依赖 Hub 在线环境，测试需要 mock | P0 测试覆盖不足 | 构建 comprehensive mock server（基于 `responses` / `pytest-httpx`），覆盖所有 Hub 端点 |
| Windows 进程管理差异大 | P1.1 跨平台问题 | 早期在 Windows 上测试 `ops/lifecycle.py`；使用 `pywin32` 或 `wmi` 库 |
| 测试数量激增导致 CI 时间过长 | P3.1 维护成本 | 测试分级：unit（< 1s）、integration（< 10s）、e2e（< 5min）；CI 只跑 unit + integration |
| 记忆图数据量增长导致查询变慢 | P1.3 性能退化 | 设计时引入分区策略（按月分文件），`memory_graph.py` 支持 lazy load |
| LLM API 成本过高 | P1.2/P1.5 运行成本 | 所有 LLM 调用增加缓存层；提供 `EVOLVER_LLM_MOCK=1` 测试模式 |

---

## 验收总纲

声称 **evolver.py** 追平 Node.js 版 **v1.90.0** 的最低标准（当前 evolver.py v1.89.14，详见 Sprint 10）：

1. [ ] **P0 全部完成**: ATP 完整闭环、Proxy 生产级、IDE 运行时 hooks、验证者系统
2. [ ] **守护进程稳定**: `evolver start` 可在 Windows/macOS/Linux 连续运行 7 天无崩溃
3. [ ] **测试通过**: 120+ 测试文件，pytest 全部通过，核心模块覆盖率 > 80%
4. [ ] **数据互操作**: Python 版生成的 `genes.jsonl` / `events.jsonl` 可被 Node.js 版正确读取，反之亦然
5. [ ] **CLI 等价**: 所有命令参数、退出码、环境变量行为与 Node.js 版一致
6. [ ] **文档完整**: 英文 README + 至少 1 种其他语言 README + SKILL.md + 示例

---

*最后更新: 2026-07-06（Sprint 10：v1.89.14 → v1.90.0 增补；trajectory/solo/cliContracts/recipe/host-error-classifier 等 17 项差距）*
*基于对比: evolver (Node.js v1.90.0 + v2.0.0-beta，src/ 删除单体化) vs evolver.py (Python v1.89.14, ~217 源文件, **159 测试文件**, **1609 tests passed**)；Sprint 1-9 已落地，Sprint 10 待办*
*剩余差距: 多源轨迹导出、Solo 模式、CLI Contracts(reuse/publish)、GEP Recipe 组合、host 错误分类、force-update/outbound 强化（见 Sprint 10）*
