# evolver.py 工作清单

> **现行章程**：[`演进方案.md`](演进方案.md)（**算子即基因**——零干预自进化：算子即基因，回放即裁决；版本 **1.114.0**）。
> **台账**：[`CHANGELOG.md`](CHANGELOG.md)。**归档史料**：[`演进方案_经验即证据.md`](演进方案_经验即证据.md)、[`TODO_经验即证据.md`](TODO_经验即证据.md)、[`演进方案_库即尺子.md`](演进方案_库即尺子.md)、[`TODO_库即尺子.md`](TODO_库即尺子.md)、[`RSI演进对照.md`](RSI演进对照.md)、[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)——史料里的「下一步」一律不开工。
> **并行已合入套具（维持回归绿灯）**：VISTA 机械套具见 [`TODO_VISTA.md`](TODO_VISTA.md)；Harness2 六项见 [`TODO_HARNESS2.md`](TODO_HARNESS2.md)；运行态外置十四项见 [`TODO_USABILITY.md`](TODO_USABILITY.md)。

---

## 统领准则（每项任务合入前必核）

1. **零干预新手友好检查**：该功能是否需要用户手写 JSON、手敲多步前置命令、看懂内部状态旗标、或跨窗口手解题目？若是，设计打回重做，直至一行 `evolver init` 或连接 MCP 即全自动无感完成。
2. **双轨纯洁性检查**：未过验证或 `drop` / `regression` / `confounded` 的改动，是否做到「工作区补丁原位保留不丢代码 + 返回诚实 `ok=False` 与 3 行人话修复指引 + 绝对不写正向基因金库」？
3. **减熵净行数检查**：新增抽象前先删死代码；全仓 `EVOLVER_*` 环境变量严控 $\le 35$ 个。

---

## Phase 0 — 零干预开箱自举、双轨止血与大减熵（P0 立即开工）

| 编号 | 任务项 | 精确源码落点 | 完成判据（机器可测） |
|---|---|---|---|
| **P0-1** | ~~一键零配置开箱与宿主自动注入（`evolver init`）~~ | `src/evolver/ops/init_bootstrap.py`、`src/evolver/ops/open_box.py`、`src/evolver/adapters/`、`src/evolver/cli.py` | 1. 在任意 Python 目录运行 `evolver init`（非 Git 目录在 `--yes` 或空目录安全初始化 Git + `.gitignore`，自动迁移遗留 `memory/`）；<br>2. 自动探测并幂等写入 Claude Code `.mcp.json`、Cursor `.cursor/mcp.json`、Codex、OpenCode、ZCode 之 MCP stdio 配置与 Hooks；<br>3. 后台干净子进程（剥离 `*_API_KEY`）自动基于项目自有 `pytest` / AST 健康度与确定性契约探针完成 `Project Native Baseline` + `Parent Library Snapshot` + `Anchor` 首写（严守 `O_CREAT \| O_EXCL`，`solidify` 调用图不可触达）；<br>4. 全程 **0 人工交互、0 警告噪音、`< 3s` 达成 `loop_ready=True`**。<br>**已落地（round-120..122）**：`ops/init_bootstrap.py` 全链路落地 + MCP 惰性自举 + Parent 指针收权（`allow_move` CLI 独占 + 调用图钉）+ **零污染 `.git/info/exclude` 登记**（`inject_docs=False` 不脏 `AGENTS.md`/`CLAUDE.md`，清理幻影 `gep_recall`/`gep_record_outcome` 引用，支持 `--host`/`--no-hosts`）。钉子：`tests/ops/test_init_bootstrap.py` |
| **P0-2** | ~~3-Verb 极简 CLI 主表面（`init` / `up` / `status`）~~ | `src/evolver/cli.py`、`src/evolver/ops/status_human.py`、`src/evolver/ops/autopilot.py` | 1. `evolver --help` 顶层仅突出展示 `init`、`up`（含别名 `auto`）、`status` 三大零门槛命令；其余 50+ 专家/内部子命令收纳至 `evolver internal <subcmd>`（保留旧顶层静默兼容转发，不破既有脚本）；<br>2. `evolver status` 输出纯人话面板（当前守护灯号、累计拦截/修复数、节省验证耗时、金库算子数、工作台草稿补丁），零内部旗标黑话；<br>3. `evolver up` 内置自适应滑动会话与连续 3 轮无进展自动休眠器，免除人工敲 `session start / extend / accept`。<br>**已落地（round-120..122）**：`_RootParser` 三动词主屏 + 拼写近似纠错提示（`difflib`）+ `up --project/--once` 启动横幅 + `status_human.py` 接入 L0 vs 全量基线真实 `saved_validation_seconds` 账本。钉子：`tests/ops/test_three_verb_cli.py` |
| **P0-3** | ~~终结 `soft-accept` 污染：拆分工作台草稿与金库晋升~~ | `src/evolver/gep/solidify.py`、`src/evolver/bench/frozen_gate.py` | 1. 删除 `frozen_gate.py::USABILITY_SOFT_REASONS` 中将 `drop` / `flat` / `regression` 放行为 `accept=True` 的逻辑；<br>2. 重构 `solidify.py::_handle_cascade_validation_failure`：验证失败一律返回 `ok=False, outcome="draft_preserved"`，原位保留工作区修改并同步备份至 `rejected_stashes/<run_id>`，生成精确到文件行号的 3 行 `actionable_fix`，**严禁进入正向基因/胶囊落库路径**；<br>3. 新增单测钉死：任何 `pytest`/`mypy`/`ruff` 失败或基准退化轮次，金库正向资产数严格 `+0`。<br>**已落地（round-120..121）**：`USABILITY_SOFT_REASONS` 仅留三项首轮环境缺口；验证失败与适应度退化统一走 `ok=False, outcome="draft_preserved"`（原位保补丁 + `rejected_stashes/<run_id>` 备份 + 恒 3 行 `actionable_fix` + tombstone 回收暂存蒸馏资产，正向金库严格 `+0`）。钉子：`tests/gep/test_dual_track_vault_freeze.py` |
| **P0-4** | ~~环境变量腰斩与死开关大扫除~~ | `src/evolver/config.py`、`src/evolver/gep/feature_flags.py`、`src/evolver/ops/charter_check.py` | 1. 全仓唯一 `EVOLVER_*` 环境变量从 **89 个收敛至 $\le 35$ 个**（合并同义开关至统一 `EvolverConfig` 嵌套配置）；<br>2. 删除 `feature_flags.py` 中 19 个常年 `False` 且无排期的死开关及对应不可达分支；<br>3. `uv run evolver charter-check` 中 `env_vars.met == True`（绿灯通过）。<br>**已落地（round-121..122）**：刀 A/B/C 删除 20 个死特性开关及孤儿模块；刀 D 新增统一 `EvolverConfig`（`~/.evolver/config.json` + `EVOLVER_CONFIG` JSON/路径），将全仓 `src/` 唯一 `EVOLVER_*` 从 **88 收敛至 32 个**（`<= 35`），`charter-check` 之 `env_vars.met == True` 全绿。钉子：`tests/test_config.py`、`tests/ops/test_charter_check.py` |

---

## Phase 1 — 一步到位 FSM 原子 MCP 协议、带内黑匣子与 3 秒闪电验证

| 编号 | 任务项 | 精确源码落点 | 完成判据（机器可测） |
|---|---|---|---|
| **P1-1** | ~~一步到位切换 FSM 动态门控三工具 MCP 协议~~ | `src/evolver/mcp_server.py`、`src/evolver/swarm.py`、`src/evolver/gep/lenses.py`、`tests/test_mcp_protocol.py` | 1. 废除旧 6 步手工串联工具（`swarm_boot`/`swarm_tick`/`swarm_distill`/`swarm_hypothesis`/`swarm_solidify`/`swarm_feedback`）及 `pending_tick_redirects.json` 与全部 17 个打地鼠布尔旗标（`gate_soft_continue`、`tick_again`、`session_not_failed`、`loop_fuse` 等）；<br>2. 基于 `notifications/tools/list_changed` 实现严格状态机：`IDLE` 态暴露 `evolve_begin` + `evolve_status`（首次调用自动懒自举，支持空假说 `discovery_only` 零副作用预览，开局强制前置锁定唯一假说）；`ACTIVE_RUN` 态物理隐藏 `evolve_begin`，暴露 `run_lens` + `evolve_settle` + `evolve_status`；<br>3. MCP stdio 端到端协议测试验证：宿主在 `ACTIVE_RUN` 下无法重复开局，`evolve_settle` 后自动推通知切回 `IDLE`。<br>**已落地（round-122）**：`mcp_server.py` 与 `swarm.py` 一步到位切换为 3 核心 FSM 工具 + 只读辅助面；内置四枚 `val_seal` 脱敏只读透镜（`ast_hotspot` / `import_impact` / `trace_locator` / `contract_surface`）。钉子：`tests/test_mcp_protocol.py`、`tests/test_swarm.py`、`tests/e2e/test_swarm_full_e2e.py` |
| **P1-2** | ~~周期边界带内黑匣子（终结 `relay=0%` 盲区）~~ | `src/evolver/gep/blackbox.py`、`src/evolver/gep/episode_record.py`、`src/evolver/ops/meta_report.py`、`src/evolver/swarm.py` | 1. 在 `evolve_begin` $\leftrightarrow$ `evolve_settle` 周期边界自动快照采集 `git diff`、前后 AST 节点增量、`run_lens` 调用栈、墙钟耗时与验证报告；<br>2. 无需配置本地 HTTP 代理，`meta-report` 过程核心指标（耗时、算子调用率、检查通过率、归因结果）引擎自记覆盖率达 **100%**。<br>**已落地（round-122）**：新增 `gep/blackbox.py` 飞行记录仪，接入 `episode_record` 与 `meta_report`（`panel.process_blackbox` 覆盖率 100%）。钉子：`tests/gep/test_lenses_and_blackbox.py` |
| **P1-3** | ~~AST 反向依赖图与 3 秒闪电验证漏斗（L0 / L1 / L2）~~ | `src/evolver/gep/import_graph.py`、`src/evolver/gep/solidify.py`、`src/evolver/ops/status_human.py` | 1. 纯标准库 `ast` 解析构建模块反向依赖有向图（按文件 SHA-256 增量毫秒级更新缓存）；<br>2. `evolve_settle` 默认跑 **L0 闪电门**（改动文件 `ruff` + 反向闭包关联 `test_*.py`，并跳过重复全仓 T0 重跑），中位验证耗时从 **296.4s 降至 `< 3s`**；<br>3. 金库晋升后自动在后台隔离 `eval_worktree` 异步跑 **L1 守护门**（子包 `mypy` + 回归集），发现跨模块回归自动降级算子为 `under_review`。<br>**已落地（round-122）**：`gep/import_graph.py` + `solidify.py` L0/L1/L2 分层漏斗 + `status_human.py` 真实 `saved_validation_seconds` 统计全通。钉子：`tests/gep/test_import_graph_and_lightning.py` |
| **P1-4** | ~~三层存储大一统与效用感知提示词打包器~~ | `src/evolver/gep/index_db.py`、`src/evolver/gep/prompt.py`、`src/evolver/swarm.py` | 1. 以标准库 `sqlite3`（WAL 模式）建立 `~/.evolver/workspaces/<id>/index.sqlite`，收编分散在工作区的信号频次、算子命中率、变体归因与预算状态账本；<br>2. 移除 `prompt.py` 中 24,000 字盲目尾截断，改为按信息密度与相关性效用（`utility / token_cost`）动态装配 `< 4,000 tokens` 高信噪比上下文。<br>**已落地（round-122）**：`gep/index_db.py`（字节游标增量同步 + 显式释放句柄兼容 Windows）接入 `swarm.py` 结算与算子推荐；`prompt.py` 实装 `pack_prompt_sections`（`PROMPT_TOKEN_BUDGET = 3800`，严守标准节序并显式摘要被省低效用块）。钉子：`tests/gep/test_index_db_and_prompt_packer.py` |

---

## Phase 2 — 三阶可执行算子基因（EOG）与零干预自动合成器

| 编号 | 任务项 | 精确源码落点 | 完成判据（机器可测） |
|---|---|---|---|
| **P2-1** | **`OperatorGene.v1` 模型与无网络受控执行沙盒** | `src/evolver/gep/schemas/`、`src/evolver/gep/operator_sandbox.py`（新建） | 1. 定义三阶算子结构：`lens`（只读 AST/日志诊断器）、`codemod`（可选 AST 守卫重写器）、`invariant`（最小可运行断言探针）；<br>2. 沙盒执行器强制剥离凭证、阻断 `socket`/`http`/`subprocess` 危险导入、限制只读目标路径与 `< 2s` CPU 超时；<br>3. 清理 `assets/gep/genes.seed.json` 中全部散文口号与 `node --test` 遗留项，首批内置 $\ge 8$ 个经本仓 `DEBUG.md` 验证的高频 Python 工程算子（锁竞争检测、路径分隔符审计、空信封契约核对、异常吞没定位等）。 |
| **P2-2** | **红转绿全自动算子合成器（Zero-Human Operator Synthesis）** | `src/evolver/gep/operator_synthesizer.py`（新建）、`src/evolver/gep/gene_lifecycle.py` | 1. 当 `evolve_settle` 捕获到真实「失败测试 $\to$ 通过（`newly_passed`）」且四值归因为 `helped` 时，引擎自动从前后 AST 差异与测试断言中提炼候选 `lens` 与 `invariant`；<br>2. 自动过沙盒编译门、正负样本自检门与局部事实脱敏门（`H2-2`），无需人类或宿主手写 JSON 即自动晋升入库；<br>3. 连续 5 次派发无净增益算子由 `gene_lifecycle` 自动转入 `retired`。 |

---

## Phase 3 — 双源时间胶囊真实故障集与 `--stage-exit v2` 盲测出口

| 编号 | 任务项 | 精确源码落点 | 完成判据（机器可测，本阶段关门条件） |
|---|---|---|---|
| **P3-1** | **双源时间胶囊真实故障集构建与密封（$N \ge 30$）** | `src/evolver/experiment/time_capsule.py`（新建）、`$EVOLVER_HOME/time_capsule/` | 1. **内源切片（$N_{\text{in}} \ge 15$）**：从本仓 [`DEBUG.md`](DEBUG.md) 历史真实故障提交对 `(parent_buggy_commit, child_fix_test)` 提取可离线独立运行的故障包；<br>2. **外源切片（$N_{\text{ext}} \ge 15$）**：精选外部主流宽松许可证开源纯 Python 项目（如 `pydantic`、`httpx`、`click`、`rich`、`attrs`、`more-itertools` 等）之独立自包含微型真实历史故障与官方验证单测（标注上游许可证与 commit 溯源，零网络依赖，单题 `pytest` `< 3s`）；<br>3. 全集存于仓外 `$EVOLVER_HOME/time_capsule/`，摘要哈希与 `val_seal` 密封规则入账，进化期绝对不可读取。 |
| **P3-2** | **反事实代码修复配对盲测（`--stage-exit v2`）** | `src/evolver/experiment/cli.py`、`src/evolver/experiment/agent_runner.py` | 1. 同一执行智能体、同一工具面、同一预算与 AB/BA 交错种子，在隔离 `Git worktree` 上对双源 $\ge 30$ 道真实故障执行真实代码修复并用 `pytest` 验分：Arm A（挂载进化算子金库 + 经验索引）vs. Arm B（空库 Placebo）；<br>2. **阶段出口硬判据**：Arm A 真实故障一次修复率（Pass@1）经 McNemar 配对检验显著优于 Arm B（$p < 0.01$，$N \ge 30$），**且外部开源 Python 故障子集（$N_{\text{ext}}$）净胜题数 $> 0$**（或同通过率下总修复验证耗时下降 $\ge 35\%$）；<br>3. 完整逐题复算报告写入 [`CHANGELOG.md`](CHANGELOG.md)，由人切下一 minor 版本收官。 |

---

## 守住与不做（速查）

- **守住**：一行开箱零人工干预；引擎核心不内嵌私改业务代码的黑盒主循环 LLM；父代基线首写只走独立干净自举（`solidify`/`evolve_settle` 不可触达）；`val_seal` 与仓外 `anchor` 17 项探针铁律不动；工作区补丁不误删、失败经验不入正向金库；每轮 `ruff` + `mypy` + `pytest` 必绿。
- **不做**：不保留繁琐 6 步旧 MCP 协议与 17 个补丁旗标；不让用户手解 `val` 沙箱或手抄 `.mcp.json`；不用日志阅读理解题充当阶段出口；不引入无测试支撑的 LLM Judge；不为凑 30 题编造无真实故障出处的假题。
