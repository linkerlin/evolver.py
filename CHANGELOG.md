# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Docs — 全量文档对齐 v1.111.0 实现现状
- **README.md**：实现状态段 1.105.0→1.111.0（补 v1.106–v1.111 弧线：自适应变异、
  验收门 soak、dogfood 五轮、工作流引擎；新增工作流引擎/验收门两行）；
  环境变量表补 17 个 v1.99+ 变量（HITL/HOTL/反馈/技能/门/冷却/Hub 重试/
  AUTO_HIJACK）；测试计数 3400+→3455+。
- **README.zh.md**：新增「MCP 蜂群进化」「进化工作流」「技能生态桥」三章节
  （原零覆盖）；实现状态自 2026-06-11（1250+ 测试）重写至 v1.111.0；
  环境变量表/示例表同步。
- **README.ja-JP.md / README.ko-KR.md**：主機能补蜂群/工作流条目；实现状态
  1.94.0→1.111.0；示例表补 swarm-quickstart；环境变量表补新变量。
- **examples/README.md**：Core Workflows 补 swarm-quickstart；新增「Evolution
  Workflows」小节（模板即教程）；命令速查补 mcp/workflow/gate-report/
  hitl/supervise/skills。
- **docs/env-registry.md**：`scripts/env_inventory.py` 再生成（234→252 变量）。
- **TODO.md**：指针刷新（1.94.0/3002 测试 → 1.111.0/3455 测试 + dogfood
  gated_runs=4 + EvoX 收割完毕）。
- **断链修复**：`演进方案.md` 已于 c195b82 删除但 12 处引用残留——统一改指
  尚存之 `演进方案_wikiskill对照版.md`（README×4 语言、TODO、
  SELF_HARNESS_CHECKPOINT）。

## [1.111.0] — 2026-09-04

### Added — dogfood round-5：已应用基因冷却（选择器效率，gated_runs 3→4）
- **观察**：round-3/4 的 tick 反复选中早已落地的基因（同信号仍在语料、
  同基因仍最佳匹配）——每次重派都是浪费的周期。选择器此前对「近期已
  成功固化」零感知。
- **修复**：`select_gene` 对近窗内成功固化过的基因施加**惩罚（×0.25，
  非禁选）**——并列时新候选胜出、唯一匹配仍可选；窗口只计带 outcome
  的 mutation 事件（簿记噪音不稀释）；事件尾加载独立于
  `enable_event_history`（该 flag 默认关，曾令冷却静默失效——本根因
  由 gate 前实证发现）。实证：同信号下选择从已落地的
  `gene_hub_retry_helper` 切换到从未应用的 `gene_degraded_local_dispatch`。
- 新配置：`EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS`（默认 5）/
  `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY`（默认 0.25）；8 个新测试；
  新基因 `gene_applied_cooldown`；引擎提交 1bc35c3。
- 工作流 gate 首次逮住真实违规（测试文件 RUF005）——innovate 模板
  `on_fail: skip` 容忍并如实记录，修复后经 solidify 权威级联全绿。

## [1.110.1] — 2026-09-04

### Fixed — dogfood round-4（repair 工作流首个实战周期，gated_runs 2→3）
- **`swarm_distill` 静默零产出**：非空响应但零资产提取时（纯文本摘要、
  无 ```json 块），返回值只有 `genes: 0` 且无任何指引——宿主无从自纠。
  现附 `hint`（期望的资产块形状 + `Gene.category` 合法枚举）并把
  `next_action` 置为 `resubmit_with_asset_blocks`；格式损坏但存在块的场景
  validation errors 与 hint 双信号并列。3 个新测试钉住（hint 触发/valid
  无 hint/坏类别 hint+errors）。
- 本轮为 **repair 模板工作流首个实战周期**（mutator → gate 真实级联
  三阶段绿 → 审批），与 round-3 的 innovate 模板互补；引擎提交 d68a7fc，
  爆炸半径恰 2 文件。新基因 `gene_distill_format_hint` 入库。

## [1.110.0] — 2026-09-04

### Added — EvoX 工作流收割：协作即数据（YAML 工作流 + 角色节点 + 级联门）
- **YAML↔DSL**：工作流 spec 支持 YAML 载入/导出（`load_spec` 按后缀分派、
  `dump_spec_yaml` 往返）——工作流成为可 diff、可进化的数据资产；`pyyaml`
  转正式声明依赖。
- **协作模式 = 节点**：`agent`/`approval` 步骤携带 `role`/`instruction`/
  `risk_reason` 元数据，`awaiting_agent()` / `awaiting_approval()` 向宿主
  执行器与人类审批者声明「现在该做什么」；WAL 等待事件记录角色。
- **`gate` 步骤**：引擎侧直跑 fitness 级联（ruff→mypy→pytest，与 solidify
  同源命令规格）；失败默认终结工作流，`on_fail: skip` 容忍并记录判定。
- **捆绑模板**：`repair`（摩擦修复回路：agent 变异 → 级联门 → 发布审批）
  与 `innovate`（探索回路：弱信号创新 → 级联门容忍失败 → 去留审批）；
  `evolver workflow templates` 列出。
- **MCP 三工具**：`swarm_workflow_run`（文件或模板启动）、
  `swarm_workflow_act`（approve/reject/complete/resume/cancel）、
  `swarm_workflow_status`（全量状态 + 宿主待办）。CLI `workflow` 增
  `templates`/`awaiting`/`complete` 动词，`run` 收 YAML 与 `--template`。

> 设计注：未另造 DAG 引擎——Sprint 24.10 既有持久化引擎（WAL + 快照 +
> 重试退避）已是外部驱动状态机；EvoX 收割以四处增量（YAML/角色/门/模板）
> 落于其上，`agent` 步骤等待面即蜂群宿主接口。

## [1.109.0] — 2026-09-04

### Added — dogfood round-2：验收门开始积累真实数据（首个 gated run）
- 级联修复后重放 round-2 变异并 `solidify` 成功：`gene_hub_retry_helper`
  （`_post_with_retry` 共享重试策略，fetch_tasks 与 send_heartbeat 统一走
  同一指数退避；None timeout 回退 `HTTP_TRANSPORT_TIMEOUT_MS`）——引擎提交
  a576564，`ValidationReport` 三阶段 overall_ok=True（216s），爆炸半径恰为
  8 文件（运行态过滤持续生效）。
- **验收门首个 gated run 落账**：`gate-report` gated_runs 0 → 1，
  `acceptance_result` 随事件持久化，verdict 诚实停在 collecting（< 20）；
  转正开关仍由人类掌握（`EVOLVER_ACCEPTANCE_SHADOW=0`）。

### Fixed — round-2 级联真实执行后暴露的存量闸门债
- **15 个跨平台 mypy 错误清偿**（此前级联从未真正跑过 mypy stage，v1.108
  venv 修复后才暴露）：winreg/windll/creationflags/CTRL_BREAK_EVENT 等
  Windows-only 属性统一改 `getattr(module, name, default)` 惯用法（运行时
  行为不变）；`os.getloadavg` 改 getattr 探测路由 fallback；删除 4 处已
  漂移的 unused-ignore（sandbox_executor×3、winreg import×1）。
- **测试隔离缺陷（dogfood 第 4 缺陷）**：`test_repair_loop_circuit_breaker_
  empty` 直读宿主仓库真实 `events.jsonl`，round-2 的 repair+failed 真实
  事件使其宿主相关地失败——补 `GEP_ASSETS_DIR` 隔离。

## [1.108.0] — 2026-09-04

### Added — dogfood round-1：蜂群在真实仓库完成首轮自主进化
- 首次以宿主执行器身份跑通全闭环：`swarm_hook_event`（真实错误信号）→
  `swarm_tick`（真实 21KB GEP dispatch，选中 gene_gep_repair_from_errors，
  信号聚焦活记忆摩擦点 f001 hub_offline）→ 最小忠实变异 → `swarm_distill`
  （新基因 gene_hub_fetch_resilience 入库）→ `swarm_solidify`（引擎提交
  cb1c1d4）→ `swarm_feedback`。
- 变异本体：Hub `fetch_tasks` 增加一次指数退避重试（f001「retry with hub
  fetch resilience」）——`EVOLVER_HUB_FETCH_RETRIES`（默认 1）/
  `EVOLVER_HUB_FETCH_RETRY_BACKOFF_MS`（500ms）；三个新测试钉住
  重试后成功/禁用回退/失败透传。

### Fixed — dogfood round-1 暴露的两个引擎缺陷
- **运行时状态混入变异提交**：守护实时写的 memory/、.evolver/、
  evolver/.config/ 文件被 `_commit_mutation` 一起提交、把爆炸半径从 3 文件
  虚增至 42——新增 `_is_runtime_state` 过滤（提交目标与爆炸半径一致排除）。
- **裸 venv python 下级联全跳过**：PATH 无 ruff/mypy/pytest → 全部 stage
  skip → unvalidated success（本轮未积累 gated run 的直接原因）——
  `get_fitness_cascade_commands` 回退解析 `<sys.executable 目录>/工具`，
  子进程级测试复现真实场景（清洗 PATH 后三阶段全部解析为绝对路径）。

## [1.107.0] — 2026-09-04

### Added — acceptance-gate soak report（验收门 soak 报告与转正判定）
- `evolver gate-report [--json]`：聚合 shadow 事件为 interception/false-kill
  指标（既有 `summarize_acceptance` 增加时间窗），并给出**转正判定**
  （`gate_soak_recommendation`）：collecting（样本 < `EVOLVER_GATE_SOAK_MIN_RUNS`，
  默认 20）/ ready（interception 落 [0.05, 0.5] 且 false_kill ≤ 0.1）/
  over_intercepting / under_intercepting / false_kill_high。转正开关
  （`EVOLVER_ACCEPTANCE_SHADOW=0`）仍由人类决定——报告只回答"数据是否支持"。
- 真实复盘（本仓库）：gated_runs = 0——守护周期从未走到被验收门打分的
  solidify，soak 样本为零，verdict = collecting；转正前需先积累真实
  gated runs（如经蜂群跑若干轮真实变异）。

## [1.106.0] — 2026-09-04

### Added — feedback-adaptive mutation bias（EvoX 自适应变异率收割）
- `gep/adaptive.py`: 统一评估反馈 E 通道（v1.99）现在直接调制策略权重——
  降级连击（≥3 连续 degraded）→ repair 偏置；收敛平台（stddev < 0.01 且
  均值 ≥ 阈值，EvoX AFlow 收敛判据）→ novelty 枢转；混合/样本不足保持
  中性。权重重归一化并 clamp，verdict 随 `policy["adaptive"]` 进入 GEP
  提示词的 strategy_policy 行与周期事件。`compute_adaptive_strategy_policy`
  接线；`swarm_status` 暴露 `feedback.mutation_bias`。反馈日志为空即 no-op
  （CLI/守护用户不受影响）。`EVOLVER_ADAPTIVE_MUTATION`（默认 on）与
  `EVOLVER_ADAPTIVE_MUTATION_SHIFT`（默认 0.2）可调。

## [1.105.0] — 2026-09-04

### Added — full-coverage swarm E2E（全覆盖 E2E + 真实 LLM 进环）
- **Tier A（始终运行）**: `tests/e2e/test_swarm_full_e2e.py` 经真实 stdio 子进程走遍整个 MCP 表面——全部 swarm/经典工具、四只 `evolver://*` 资源、`evolver_swarm` prompt、auto-hijack 指令变体、HITL 自动批准 + HOTL pause/direct/veto 线上流。
- **Tier B（`-m llm`，需 `DEEPSEEK_API_KEY`）**: **deepseek-v4-flash 真实扮演宿主执行器**——tick → LLM 执行真实 GEP dispatch 提示词 → distill → feedback → 二次 tick。LLM 客户端只存在于测试 harness，引擎保持零 LLM 依赖。

### Fixed
- MCP 工具结果必须优先读 `structuredContent`（规范要求顶层为对象，SDK 将非 dict 返回包为 `{"result": ...}`；`content[].text` 对 list 只含首元素）——已文档化并应用于全部 MCP 测试客户端。

## [1.104.0] — 2026-09-04

### Added — skill ecosystem bridge（技能生态桥，EvoX SkillRegistry 概念收割）
- `gep/skill_assets.py`: 多根优先发现（工作区 `.agents`/`.claude` skills > 用户 `~/.agents`/`~/.zcode`/`~/.claude` skills > 内置）+ 同名遮蔽；同步为 `gene_distilled_s2g-*` 基因入库，使宿主生态技能参与信号匹配。CLI `evolver skills list|scan|sync`；MCP `swarm_skills`；`EVOLVER_SKILL_ROOTS` 覆盖根（顺序即优先级）。

### Fixed
- 技能基因原用 skill2gep 本地哈希公式，被资产库内容哈希校验静默丢弃——同步时改用权威公式重算 `asset_id`。

## [1.103.0] — 2026-09-04

### Added — MCP surface completion + protocol E2E
- MCP resources: `evolver://status` / `evolver://instrument-prompt` / `evolver://dispatch/last` / `evolver://events/recent`。
- 工具注解: readOnlyHint（只读工具）/ destructiveHint（`swarm_solidify`）。
- `tests/test_mcp_protocol.py`: 真实子进程 stdio JSON-RPC 协议 E2E。

### Fixed — 测试套件首次全绿（3377 通过）
- `feature_flags`: 源码级大小写不敏感 env 回退（POSIX 上小写 `EVOLVER_FF_enable_xxx` 曾被静默忽略）。
- Bedrock 流测试: dev 组补 boto3。Solo CLI 测试: 接受 POSIX max-cycles 交接退出码；替代进程指向 no-op 杜绝孤儿重生链。macOS `/var → /private/var` 符号链接断言改比较 resolve 路径。self-repair 测试: `git checkout -B`（defaultBranch=main 下幂等）。

## [1.102.0] — 2026-09-04

### Added — hooks integration for MCP hosts（双轨）
- `swarm_hooks`（status/install/uninstall，包装 setup-hooks）供支持文件钩子的宿主；`swarm_hook_event` 进程内桥（session_start/session_end/signal_detect → 共享信号检测器 → pending_signals）供 MCP-only 宿主。instrument prompt 第三章（Hooks 集成）指导择轨。README 增 MCP 配置指南（ZCode / Claude Code / Cursor）。

## [1.101.0] — 2026-09-04

### Added — HOTL human-on-the-loop supervision（人在环上监督层）
- `gep/supervision.py`: running/paused 状态机（优雅排水）；veto 子串模式（tick 命中扣发提示词 + solidify 阻断，纵深防御）；directive 转向指令注入下轮信号；降级连击绊线自动暂停（`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`）。CLI `evolver supervise`；MCP `swarm_supervise`。与 HITL 正交互补，补全自治光谱。

## [1.100.0] — 2026-09-04

### Added — HITL fail-safe approval gate（EvoX HITLManager 概念收割）
- `gep/hitl.py`: `swarm_solidify(skip_validation=true)` 过审批门——`EVOLVER_HITL_MODE=on` 阻塞待 `evolver hitl approve`，TTL 超时 fail-safe 拒绝，按 subject 幂等（杜绝 approval-shopping），off 模式仍全程审计。CLI `evolver hitl list|approve|reject`；MCP `swarm_approvals`/`swarm_approval_resolve`。
- 反馈稳定性观察面（EvoX 双收敛判据）: `swarm_status` 报告近期反馈分数 stddev。

## [1.99.0] — 2026-09-04

### Added — unified evaluation feedback E（统一评估信号，EvoX 概念收割）
- `gep/feedback.py`: `swarm_feedback` 上报 `primary_score`/`metrics`/`textual_gradient` 三分离；降级报告注入 `swarm_feedback:degraded` + 梯度信号键走 pending_signals 通道（与 autopoiesis 摩擦同路）驱动下轮修复偏置；全量记 `feedback.jsonl`。

## [1.98.0] — 2026-09-03

### Added — swarm evolution via MCP host-agent takeover（蜂群宿主接管，关闭"半开环执行断层"）
- 引擎不自建 LLM API 调度：经 stdio MCP 连入的宿主 Agent 即执行器。注入方案概念收割自 nanoclaw.go（instructions + boot 工具）并叠加正式 MCP prompt 作为显式 instrument。
- `evolver.swarm`: 接管提示词 + 传输无关闭环工具（boot/tick/distill/solidify/report/status）；引擎 stdout 全捕获（stdio MCP 独占 stdout）；`swarm_state.json` tick 台账；preflight abort / user-lock 冲突优雅返回 stop_and_report。
- `evolver.mcp_server`: `evolver_swarm` prompt + swarm 工具面；`EVOLVER_SWARM_AUTO_HIJACK=1` 无人值守接管。dispatch 将组好的 GEP 提示词存入 ctx 供进程内调用方。

### Changed — S30 dependency layering（依赖分层治理）
- fastapi/uvicorn 移入可选 `evolver[server]` extra；server 命令缺依赖快速失败并提示安装；新增依赖分层守护测试。

### Fixed
- 会话级 `EVOLVE_LOAD_MAX` 屏蔽环境负载，根治全周期测试的环境性抖动。

## [1.97.0] — 2026-09-02

### Added — handover items closed (演进方案_wikiskill对照版.md §8 移交余项)
- **S27.2 patterns projection**: new `gep/wiki_projection.py` — regenerates `wiki/patterns/{friction.md, preferred-genes.md}` as deterministic human-readable projections of machine-layer state (LESSONS_LEARNED friction points, memory_graph `preferred_by_signal`), rewrites `wiki/index.md`, audit-commits to the wiki repo. Pages carry no timestamps (git log is the provenance) so projections are byte-idempotent. Trigger: `evolver report`.
- **S27.4 run report**: new `gep/report.py` + `evolver report [--output] [--limit] [--no-project]` — per-cycle verdict counts (success / failed / unvalidated / fitness-gate verdicts / acceptance rejections), the r_best ledger per measurement domain, wiki layer counts, and a **negative-results section rendered as-is** (most recent first; empty window says so instead of claiming success). Runs the patterns projection first unless `--no-project`.
- **S28.2 launch-failure signalization**: `launch_failure_detected` joins `OPPORTUNITY_SIGNALS` + new `signals.count_launch_failures(rows)`; `evolver trajectory` export counts launch failures in the exported rows and queues `launch_failure_detected` via the existing pending-signals pipe — the next cycle's signals phase consumes it automatically ("couldn't start" ≠ "didn't work", wikiskill Run-4 lesson, now wired end-to-end).

### Fixed
- **bench pytest-fast false failure (审阅勘误 #7)**: the health task's hardcoded 300s timeout sat BELOW the real not-slow suite duration (~310s) → `TimeoutExpired` → permanent R=0.5 on a green repo. The bench timeout now reuses the cascade's `FITNESS_PYTEST_TIMEOUT_MS` (600s, env-overridable) — one source of truth for the same suite; regression test pins bench ceiling == cascade ceiling. Post-fix `evolver bench run` measures R=1.0.

## [1.96.0] — 2026-09-01

### Changed — Sprint 26: quantitative fitness promoted to DEFAULT path (演进方案_wikiskill对照版.md §S26; mirrors the wikiskill gating loop)

- **Fitness cascade ON by default** (`enable_fitness_cascade: true`): every solidify now runs the engine-owned validation cascade (ruff → mypy → pytest, short-circuit, per-stage timeouts). Commands whose executable is missing from PATH are skipped with a warning, so non-Python workspaces degrade to the legacy `mutation.validation` path instead of failing every cycle (`solidify.get_fitness_cascade_commands`).
- **Honest outcome scores**: a validated success lands the MEASURED cascade score; an unvalidated success (skip_validation / empty cascade) lands `score: null` + `unvalidated: true` instead of a fabricated `1.0` (`solidify.py` — closes the §13 audit's headline gap).
- **Failure events ON by default** (`enable_failure_events: true`): every terminal solidify failure lands an EvolutionEvent — silence is not an honest outcome.
- **Acceptance gate ON by default, shadow mode first** (`enable_acceptance_gate: true` + `EVOLVER_ACCEPTANCE_SHADOW=true`): T0 verdicts are computed and recorded on events (shadow markers) but never enforced during the soak window. Enforcement: `EVOLVER_ACCEPTANCE_SHADOW=0`.
- **Strict-improvement fitness gate (r_best ledger)**: new `gep/fitness_state.py` (`evolution_fitness_state.json`: baseline / r_best / decision history). Every measured solidify score is compared against r_best (`R > R_best`, strictly greater — first measurement establishes the baseline, like the wikiskill establishing run). Shadow period: verdicts land on events as `fitness_gate`; enforcement (rollback of `no_improvement` mutations) via `EVOLVER_FITNESS_GATE_ENFORCE=1`. Unmeasured (None) scores never touch the ledger.
- **Wiki knowledge layer (S27)**: new `gep/wiki.py` — `<EVOLUTION_DIR>/wiki/` with its OWN git repository (audit commits only, never rolled back): `README.md` / `index.md` / `log.md` (one line per accepted mutation) / `skill-impact.md` (full record of every rejected / non-improving mutation) / `patterns/`. Solidify projects every terminal outcome into the wiki: accepted → log; validation-failure / novelty-duplicate / acceptance-rejection / fitness-enforcement-rejection / shadow no_improvement → skill-impact entries. **Asymmetric rollback verified by tests**: workspace `stash` and even `reset --hard` leave the wiki byte-identical (skills are hypotheses, the wiki is evidence). **Rejection memory is main-path**: every GEP prompt now carries a `## Wiki Impact` block listing recent rejection headings ("do NOT repeat these approaches") — the wikiskill skill-impact contract, wired by default.
- **Cascade failures carry lineage**: `_handle_cascade_validation_failure` events now include GEPA lineage fields (parent_event_id), matching the novelty-rejection path.
- **Repo dogfood / state hygiene**: `evolver/.config/disk_flags.json` untracked and gitignored — it is runtime hot-reload state (auto-seeded from `DEFAULT_FLAGS` on first run), not source; tracking it made every test run dirty the worktree (first slice of 演进方案 S30.8 "runtime state out of the repo").
- Test infrastructure: `tests/conftest.py` swaps in a workspace-neutral cascade command set globally (sandboxed workspaces have no src/tests for host tooling); legacy-path tests opt out via `set_flag("enable_fitness_cascade", False)`.

### Added
- **Built-in deterministic benchmark pack (S26.1 completion)**: `bench/builtin_pack.py` + `evolver bench init [dir]` — 12 tasks across five families (spec-literal / extract / code / json / traps) aimed at classic agent failure modes; byte-identical across generations; the double-exclusion trap asserts at GENERATION time that its clauses do not compensate (wikiskill bench discipline). `load_pack` accepts both the wrapped `{"pack_version","tasks"}` file and bare wikiskill lists. Self-consistency tests now pin ALL FOUR graders (exact / contains / json_field / code_stdout), closing review-erratum item 5.
- **Launch-failure honesty (S28.2)**: `Trajectory.activity` derived field (`launch_failure` / `active`, `__post_init__` from `stats.tool_call_count`) — a zero-tool-call session is exported as a launch failure, NOT behavioral evidence (wikiskill Run-4 lesson, architecture-level). The classification rides every exported JSONL row for downstream distill/signal consumers.
- **Paired statistical comparison (S30)**: new `bench/compare.py` + `evolver bench compare <a.json> <b.json> [--alpha]` — answers "did the mutation actually help?" with an exact two-sided binomial test on discordant pairs (hand-written, stdlib-only; known-value contract `(10,0) → 2/2**10`). `bench run --output` persists per-task results as the comparison input. A verdict requires BOTH the correct direction AND p ≤ alpha — small samples honestly report `no_significant_difference` (3:0 sweeps do NOT reach significance, and the tests pin that). Task-set mismatch is a hard error: comparing different task sets is meaningless.
- **Gene proposals — mechanical mutation application (S29)**: new `gep/proposal.py`. Agents submit a `GeneProposal` JSON (`patch` / `create` / `no_action` with `append` / `replace` / `insert_after` edits); the engine applies it mechanically with hard validation: **anchor text must match exactly and uniquely** (a hallucinated or ambiguous anchor rejects the WHOLE proposal — validate-all-first, no partial application), file paths must stay inside the workspace and out of forbidden dirs (.git/.venv/node_modules/.evolver), and `no_action` is a first-class outcome. CLI: `evolver apply-proposal <file>`; flow: apply → `evolver solidify` (cascade + gates). Same-batch same-file edits compose sequentially and fail loudly if a batch disturbs its own anchor.
- **Immutable evidence layer (S28.1)**: new `gep/evidence.py` — `<GEP_ASSETS_DIR>/evidence/<run_id>/` keeps the FULL scene per solidify run (event + validation results + fitness verdict + gate). Architecture-level immutability: writing the same evidence file twice raises `FileExistsError` — no silent history rewrite; replays reproduce byte-identical files. Wired on the success and cascade-failure paths (best-effort).
- **Environment variable registry (S25.5)**: `scripts/env_inventory.py` (pure stdlib AST scan) + `docs/env-registry.md` — 234 unique variables audited with their read mechanisms; the pruning baseline for S30.4 governance.
- **`evolver bench` subsystem (S26.1)**: `src/evolver/bench/` — the measurement surface of the fitness revolution. `bench list` / `bench run [--no-record]`: weighted built-in health tasks (ruff / mypy / pytest-fast; PATH-missing tasks skip like the cascade) scored into the r_best ledger (`record_measurement(source="bench")`). Task-pack library in wikiskill task format (`{id, split, prompt, sandbox, grader}`): validation, sandbox materialization with force-cleanup (phantom-scoring defense), and four deterministic graders (`exact` / `contains` / `json_field` / `code_stdout`, all 0.0/1.0, never crash, missing deliverable = 0).
- **Semi-automatic pack executor (S26.1c)**: `bench prompt <id> --pack tasks.json` materializes the sandbox (force) and prints the agent prompt (absolute WORKING DIRECTORY, no-outside-exploration rule — the engine never runs an agent, the prompt is the interface); `bench grade <id> --pack` scores the deliverable (single score, never moves r_best); `bench run --pack --split val` aggregates a split into one R measurement. **S26.4 split discipline**: gate ONLY on val — train splits are excluded from gate R by construction; pending sandboxes (agent hasn't run) are reported and excluded, and an empty graded set records nothing.
- `tests/gep/test_sprint26_promotion.py`: promotion contract (default flags, shadow default, PATH filtering, measured vs unvalidated scores, graded failure + lineage).
- `演进方案_wikiskill对照版.md`: evolution plan audited against the wikiskill reference implementation (arXiv:2608.27454) — S25–S30 roadmap.

### Fixed — dual-axis review remediation (2026-09-01)
- **boto3 mis-removal (P0)**: the S25.4 audit's "0 references" claim was wrong (scan depth missed 3 lazy imports in `proxy/router/messages_route.py`); boto3 restored into the optional `[bedrock]` extra — the Bedrock relay's own not-installed fallback made it optional by design. Audit doc corrected.
- **r_best domain mixing**: the fitness ledger is now domain-separated (`cascade` / `bench:health` / `bench:pack:<split>` routed from the measurement source) — a cascade 1.0 can no longer permanently lock out bench improvements; legacy top-level state auto-migrates to the `cascade` domain; cross-domain isolation is test-pinned.
- **wiki parent-tracking hole**: `wiki.ensure()` now idempotently appends the wiki path to the parent repo's `.gitignore` — a parent auto-commit + `reset --hard` can no longer roll back "never-rolled-back" knowledge (new scenario test: parent commits everything, hard-resets, wiki survives and was never tracked).
- **S26.3 acceptance #2**: new end-to-end harmful-mutation test (proposal injects a harmful edit → cascade vetoes → working tree rolled back → failed event + wiki evidence land).
- **Review cleanup**: shared `_failure_event()` builder deduplicates the four rejection-event shapes in solidify; `_now_iso_ms()` helper; `Trajectory.activity` typed `Literal`; dead branch removed from `env_inventory.py`; `baseline_snapshot.py` parses the version with `tomllib`; new tests use `set_flag(..., persist=False)` (no more disk-flag pollution); new modules annotated "No Node.js equivalent" per the docstring convention.

## [1.95.0] — 2026-08-15

### Added — Sprint 22/23: methodology hardening (演进方案.md §13; all behind feature flags, default OFF; flag-off behavior byte-identical with 1.94.0)

- **Open-loop closures (22.1)**: `enable_event_history` (EvolutionEvent history feeds signal modulation — saturation/dedup/ban_gene/plateau revived), `enable_gap_outcome_inference` (error-cleared ⇒ success bookkeeping, double-record guard), innovation-failure outcomes (ROI denominator), ATP spawn persisted to disk, `enable_windows_load_guard` (psutil CPU proxy where `os.getloadavg` is missing).
- **Quantitative fitness (22.2)**: `enable_fitness_cascade` — engine-owned validation cascade (ruff → mypy → pytest, short-circuit, per-stage timeouts); graded failure score (stage progress + pytest pass rate) flows into memory graph / innovation / events; untrusted `mutation.validation` (LLM-distilled) is never executed in this mode; failed EvolutionEvents land in `events.jsonl` (revives repair-loop breaker).
- **UCB1 selection (22.3)**: `enable_bandit_selection` — parent sampling `score × (1 + mean + c·√(ln N/nᵢ))`; `get_memory_advice` exposes per-gene `geneStats`; `--review` stays deterministic (module-level `_loop_review_mode`).
- **Niche archive (22.4)**: `enable_niche_topk` — per-signal top-3 preferred genes (solidify success anchors #1); permanent bans become 30-day probations (`probation_by_signal`).
- **Acceptance gray-scale (22.5)**: `EVOLVER_ACCEPTANCE_SHADOW` — gate verdicts recorded, never enforced; `acceptance/report.summarize_acceptance()` (interception / validation-disagreement / false-kill-risk).
- **Lineage lessons (22.6)**: `enable_lineage_lessons` — `parent_event_id` on events (fills the always-empty prompt slot) + "Lineage Lessons" block (selected gene's recent failures) in the GEP prompt.
- **Novelty gate (23.1)**: `enable_novelty_gate` — pre-cascade rejection sampling (ShinkaEvolve η=0.95) over added-line sets vs capsule diffs / event snapshots / rejected fingerprints; reversals do not false-positive.
- **Operator bandit (23.2)**: `enable_operator_bandit` — mutation category UCB1 sampling over graded outcomes; keyword category keeps the dominant prior; `force_category`/drift authoritative; personality safety downgrade still applies.
- **ATP spawn bridge (23.3)**: `enable_atp_spawn_bridge` — picked-up ATP tasks emitted as `sessions_spawn` when bridge mode is active.
- **Auto-commit (soak)**: cascade-mode success commits the accepted mutation (atomic evolution steps) so later failure rollbacks stop at the last acceptance.

### Fixed
- **Gap outcome attribution**: inferred outcomes landed under the current (post-fix, empty-signal) key — disconnected from the attempt niche, breaking geneStats/UCB1 data. Now attributed to `last_action`'s key.
- **Rollback cwd family (3 sites)**: cascade-failure / novelty / acceptance-gate rollbacks lacked `cwd` — would stash the ENGINE's repo instead of the workspace.
- **Rollback destroyed accepted work**: `stash --include-untracked` ate engine state (`events.jsonl`) and every prior accepted-but-uncommitted mutation in no-gitignore workspaces; rollbacks are now tracked-only + selective disposable-untracked disposal (engine dirs, `.pytest_cache`, `__pycache__` spared).
- **T0 acceptance gate blind to test deletion**: re-froze the current test set per run (deleted tests vanished from the denominator — "delete tests to go green" passed). Frozen IDs now load from the persisted baseline snapshot.
- **CI version assertion**: `__init__.py.__version__` was still 1.93.0 while CI asserted 1.94.0 (latent red) — now in sync at 1.95.0.
- **Novelty fingerprint pollution**: engine state dirs / `__pycache__` / committed engine-state diffs diluted or poisoned the fingerprint; fingerprint now pathspec-filtered and split into (full, added) views.

### Verified
- 3-cycle E2E + 12-cycle soak (scripted mutation mix): graded scores, novelty rejections, shadow interception (del_tests_break case: cascade green + T0 regressed), lineage chain, niche stats — all green.
- 3100 tests, ruff/mypy clean; flags default OFF keep 1.94.0 behavior.

## [1.94.0] — 2026-08-11

### Added
- **Sprint 20 — v1.94.0 parity**（锚定 Node evolver v1.94.0）：
  - **sandbox 安全加固**：`sandbox_executor` 禁 `--inspect*/--watch*/--conditions/-C` node flags（GHSA-jxh8-jh77-xh6g 后续）；`--version/-v/--help/-h` 豁免脚本文件要求（#607–609）。
  - **publish 验证闸**：loose-asset 发布默认沙箱可跑命令 `node --version`；沙箱必拒的命令发布时 400（`PublishValidationError`）；Capsule 同载 validation；`policy_check.is_validation_command_allowed` 与 sandbox 门共用实现零漂移。
  - **Claude 上下文基因家族** `gep/context_routing_gene.py`：6 基因内容寻址（prompt-budget ledger / schema routing / tool-schema lazy-load / skill-manual routing / transcript handoff / memory-index budget）；`asset_store` seed 升级追加机制（标记≥2 / 仅补缺 / filelock / 不覆写用户 store）；`genes.seed.json` 对齐 808 行语义。
  - **feedbackEnvelope** `gep/feedback_envelope.py`：label/indecision/conflict/attention-aware uncertainty/聚合契约（纯测试契约行为重写）。
  - **12 个上下文膨胀信号**：claude_code_context_bloat / context_explosion / tool_schema_bloat / skill_list_bloat / skill_manual_bloat / transcript_context_bloat / conversation_handoff_bloat / memory_index_budget / prompt_budget_measurement / lazy_load_schema / schema_routing_gene_request / token_budget_overflow（双语正则）。
  - **ssePlannedClose**：SSE duration ≤300s（Hub 上限）、planned-close 一次性闩锁、fetch 回退帧解析（event/data 分派）、计划关闭重置重连退避至 5s。
  - **solidify 过程助手** `gep/solidify_helpers.py`：blast 严重度阶梯 / 目录分组 / 漂移检测 / 失败原因合成 / 过程评分（含 hollow-commit 守卫）/ 基因类别选择 / forbidden-path 守卫。
- **a2a_protocol 契约套件**：6 → 55 用例（消息构建、fetch/publish 包络、execution_trace 合成、签名、unwrap、post_hub_envelope 错误路径、node_id 文件）。
- **工程闸门全绿**：ruff 885→0、`ruff format` 544/544、mypy strict 44→0；全量 **2900+ 用例通过**。
- **基线失败测试修复**：solo（Windows exit-1 平台分支）、lifecycle×2（store 旧前缀权威性 + EVOLVER_HOME 隔离）、webui×3（陈旧测试形状对齐分页契约）、router（node_id 缓存重置）。

### Changed
- Package version **1.89.14 → 1.93.0 → 1.94.0**（声明 Node evolver **v1.94.0** parity）。
- ruff 配置：移植模式规则（PLC0415/ARG00x/PLR09xx/PLW0603/SIM102/117/RUF001）全局豁免并附理由；tests/** 惯用法豁免。
- README Implementation Status 刷新至 Sprint 20。

### Notes
- a2a 深度剩余：心跳状态机 / 事件投递 daemon 级 E2E 仍可加深（演进方案.md Sprint 21）。
- v2.0.x（Node 独立发布线）评估列 Sprint 21.5。

## [1.93.0] — 2026-07-31

### Added
- **A14** `experiment/trigger_shift.py` — offline trigger/context overfitting evaluator + package exports.
- **A15** `scripts/harness_governance_check.py` — PR CI harness/evaluator governance gate.
- **A16** `cli_options.py` — proxy path flags `--home/--store/--settings/--env-file` on `evolver proxy`.
- **solidify learning helpers** — `classify_failure_mode`, `adapt_gene_from_learning`, `build_soft_failure_learning_signals`.
- **a2a `build_publish`** — single-asset publish + Capsule execution_trace guard.
- **schema/prompt enum consistency** — `render_enum*` + explore in GEP prompt schemas.
- **Static guards** — dotenv load order (#460), adapters `py_compile` (#542), Hub egress coverage (C7).
- **Direct solidify suite** — `tests/gep/test_solidify.py`.
- **git_ops pure-function suite** — path normalize/protected/constraint contracts.
- **WebUI observer depth** — get_asset_overview, list_candidates, list_asset_calls, get_lineage;
  list_runs/get_run multi-source aggregation; API routes /api/assets/overview, /api/candidates,
  /api/asset-calls, /api/runs?view=list, /api/runs/{id}.

### Changed
- Package version **1.89.14 → 1.93.0** (declared Node evolver **v1.93.0** parity baseline).
- CI: Ubuntu 3.12/3.13 required; **Windows advisory** job (`continue-on-error`) for platform regressions.
- README Implementation Status refreshed for Sprint 18–19 surfaces.

### Notes
- Depth gaps (a2a protocol surface, solidify contract breadth, observer polish) remain tracked in `演进方案.md`.

## [Unreleased] — Sprint 10: v1.89.14 → v1.90.0 catch-up

### Gap 1: Trajectory export — foundation + decryption + session sources (G10.1, partial)
- `gep/trajectory/` (new package): ports the core of `trajectoryExport.test.js`.
  - `builder.py` — `build_trajectories()` / `build_trajectory_from_rows()`:
    group proxy-trace rows by session into `evomap.coding_trajectory.v1`
    trajectories; per-turn extraction (provider, endpoint, response_id,
    previous_response_id, request/response bodies, reasoning, encrypted_content,
    per-turn tokens, error); tool-call extraction across Anthropic `/v1/messages`,
    OpenAI `/v1/responses`, `/v1/chat/completions` (declared tools vs actual
    invocations; Anthropic `tool_use` deduped by id); **full streamed
    tool-argument reconstruction** (Anthropic `input_json_delta`; OpenAI Chat
    delta + full-snapshot dedup; OpenAI Responses delta + `.done` override);
    Bedrock provider normalisation; language detection (keywords + file
    extensions); failure-correction marking; test-execution / code-edit /
    `test_commands` detection from tool inputs; stats (`turns`, tokens,
    `has_tool_calls`, `tool_call_count`, `tool_types`, `has_test_execution`,
    `has_code_edit`, `test_commands`).
  - `io.py` — `write_trajectories()`: atomic (temp + `os.replace`); a pre-placed
    symlink is **not followed** (PR #294 C4); owner-only `0o600` on POSIX.
  - `crypto.py` — `read_trace_rows_detailed()` / `decrypt_trace_row()`: AES-256-GCM
    under a node-secret-derived key with `secret_version` keyring selection;
    RSA-OAEP-SHA256 hub-key envelope unwrap with node-secret fallback;
    **fail-closed** (3 distinct messages) unless `--allow-partial`.
  - `sources.py` — non-proxy session logs: **Codex rollout** JSONL
    (`session_meta` + `response_item` records — message/reasoning/function_call/
    function_call_output/custom_tool_call/tool_search*), **Claude Code
    transcript** JSONL (`user`/`assistant` with `message.content` blocks), and
    **OpenAI generic-chat** messages JSONL (top-level role-tagged records,
    `prompt_tokens`/`completion_tokens`, `thinking`+`signature`, OpenAI
    `tool_calls`/`tool` outputs) — with reasoning turns, custom tool calls,
    tool-search events, and test-execution / code-edit / failure-correction
    detection; plus `detect_source()` classification.
  - CLI: `evolver trajectory --input <file|dir> --output [...]` auto-detects
    session logs vs proxy traces, recurses directories, and decrypts with
    `--node-secret`/`--hub-private-key`/`--node-secret-keyring`/`--allow-partial`.
- `tests/gep/trajectory/` (27 cases: 11 builder incl. full streaming + 10 crypto + 6 sources).
- **Deferred (niche vendor sources)**: Cursor vscdb (SQLite), Gemini
  CLI+Gateway, Kimi Wire — bespoke low-frequency parsers, each with its own
  format-specific test file.

### Gap 8: Force-update hardening (v1.90.0 contract)
- `force_update.py` (262→490+ lines): ports the portable subset of Node's
  `forceUpdate*.test.js` (Node-specific npx/degit/package.json/index.js/exit-78
  mechanics are N/A for Python and intentionally omitted).
  - **Sentinels** — `FORCE_UPDATE_BUSY` / `FORCE_UPDATE_NOOP` (distinct
    singletons; identity-comparable, no truthy collision).
  - **Concurrency guard** — module-level mutex in `execute_force_update()`: a
    re-entrant call mid-upgrade returns `FORCE_UPDATE_BUSY` without
    re-downloading; mutex resets via `finally` (and on throw). (Fills a gap: the
    docstring claimed a file-lock guard that was never implemented.)
  - **Idempotent floor** — `required_version` is a *minimum floor*, not an exact
    target: operator (`>=`/`>`/`=`) + leading-`v` normalisation; an install that
    already satisfies the floor returns `FORCE_UPDATE_NOOP` (no downgrade, no
    re-download). Anti-downgrade guard (#213): an unparsable current version is
    refused, not silently satisfied.
  - **Coded frozen failures** — every failure is an immutable result carrying a
    stable `code` + `detail`; `is_force_update_failure()` + `FORCE_UPDATE_FAIL_CODES`
    registry.
  - **Safe extraction** — `_safe_extract()` refuses Zip-Slip (path-traversal)
    entries (keep-list/tarball-fallback safety).
  - `report_force_update_outcome(noop/updated)` persists status (`skipped`/
    `success`); `noop` wins defensively.
- `tests/test_force_update.py` (+19 cases).

### Gap 9: Outbound sync resilience (v1.90.0 contract)
- `proxy/sync/outbound.py` (108→290+ lines): ports `proxyOutboundSync.test.js`.
  - **Body-size budgeting** — one size-bounded batch per flush
    (`EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES` env, overridable by store state after
    a 413); a single message that cannot fit is rejected, not sent.
  - **413 handling** — single-message 413 quarantines; multi-message 413 backs
    the budget down and leaves all messages pending (1 Hub call).
  - **Retryable vs terminal** — retryable per-message failures defer (status
    pending, retry count untouched, `next_retry_at` set); terminal finalises.
    `terminal` wins over retry hints (PR #301).
  - **proxy_trace gating** — `proxy_trace` dropped when
    `trace_collection_enabled` store state is `False`.
  - **Redaction** — Hub non-2xx response text redacted before persistence.
  - Rich result shape: `sent`/`synced`/`dropped`/`deferred`/`payload_too_large`/
    `error`/`responses`.
- `proxy/mailbox/store.py`: `Message.next_retry_at` field; `poll_outbound`
  skips deferred-not-due messages; new `defer()` (backoff without burning retry).
- `tests/test_proxy_outbound_sync.py` (new, 11 cases); `test_proxy_sync.py`
  updated to Node v1.90.0 `sent`=batch-size semantics.
- Encryption-envelope validation of `proxy_trace` payloads deferred to G10.1.

### Gap 5: Host Error Classifier (#571)
- `gep/host_error_classifier.py` (new): `is_host_client_error()` + non-global
  `HOST_PROVIDER_ERR_RE` — classifies 4xx provider errors (invalid_api_key /
  insufficient_quota / rate limit / MaxTokens / HTTP 4xx) with bare-number-safe
  context. `None`/non-str/empty → `False`.
- `gep/signals.py`: under a host client error the failure-streak path is
  skipped — no `ban_gene` / `failure_loop_detected` / `consecutive_failure_streak`
  / `force_innovation_after_repair_loop`; the actionable `host_llm_client_error`
  signal is surfaced instead. An LLM quota/auth storm can no longer ban a gene.
- `tests/gep/test_host_error_classifier.py` (new, 5 cases): ports
  `hostClientErrorSignals.test.js`.

### Gap 2: Solo mode (`--solo` / constrained-wild / "Mad Dog")
- `solo/` subsystem (new): `breaker.py` (network "no escape valve" hard cut) +
  `git_guard.py` (local-git-only guard, wired into `git_ops.run_cmd`) +
  `__init__.py` (banner). Solo state = `EVOLVER_SOLO` env (process-wide,
  import-race-safe).
- `cli.py`: `--solo` flag (implies `--loop`); activates before dispatch so env
  overrides + hub cut land at the source. Even a user-set `A2A_HUB_URL` is
  ignored. Validator daemon + ATP auto-spend + task pickup are hard-cut in both
  the startup path (`start_validator` returns `None`; ATP envs forced off) and
  the in-cycle path (`post_cycle` guards).
- `config.py`: `resolve_hub_url()` returns `""` under solo (no escape valve);
  new `MAX_CYCLES_PER_PROCESS` (`EVOLVER_MAX_CYCLES_PER_PROCESS`, 0=unlimited).
- `evolve/runner.py`: daemon loop honours `MAX_CYCLES_PER_PROCESS` (exits after
  N cycles — solo/CI testability).
- Fix: `cli._cmd_loop` now guards `add_signal_handler`/`remove_signal_handler`
  against `NotImplementedError` so `--loop`/`--solo` work on Windows
  (ProactorEventLoop lacks signal-handler support).
- `tests/solo/test_solo.py` (new, 11 cases): ports `soloMode.test.js`, including
  a subprocess smoke test asserting banner + service cut + clean exit.

### Stats
- **Tests**: +73 (5 host-error + 11 solo + 11 outbound + 19 force-update +
  27 trajectory); 0 regressions (1 pre-existing cognition test failure unrelated).
- **Baseline**: tracking v1.89.14 → **v1.90.0** (G10.5, G10.2, G10.8, G10.9
  closed; G10.1 trajectory core complete — proxy + full streaming + crypto +
  Codex/Claude/generic sources — Cursor/Gemini/Kimi vendor sources deferred;
  G10.3 cliContracts / G10.4 recipe pending).

## [Unreleased] — Sprint 9: v1.89.14 parity (7 gaps closed)

### Gap 1: Inert Gene Ban (#562)
- `gep/memory_graph.py`: `stable_no_error`/`heuristic_delta`/`predictive` outcomes
  now classified as **inert** — they build no Bayesian confidence and no longer
  count as successes for `preferredGeneId`.
- New `_count_trailing_inert()`: after `GENE_INERT_BAN_STREAK` (=8) consecutive
  trailing inert outcomes with no real success, the gene is added to
  `bannedGeneIds` so the selector yields null and the pipeline mutates.
- A single real success (e.g. `error_cleared`) resets the inert streak.
- 5 regression tests ported from `test/issue562InertGeneBan.test.js`.

### Gap 2: Node Secret Versioning
- `proxy/lifecycle/manager.py`: `parse_node_secret_version()`, `node_secret_version`
  property (store > env precedence), stale-secret detection (store version < env
  version → Hub rotated → clear store secret).
- `hello()`/`heartbeat()` persist the Hub-returned `node_secret_version`.

### Gap 3: Hub-Unreachable Exponential Backoff
- `proxy/lifecycle/manager.py`: `_record_hub_unreachable()` / `_record_hub_reachable()`
  / `_hub_unreachable_wait_ms()` / `hub_unreachable_backoff_ms()` — exponential
  backoff (5s→15min cap) on network errors (ConnectError/TimeoutException).
- `hello()`/`heartbeat()` check backoff before sending and record
  reachable/unreachable on success/failure.

### Gap 4: Anti-Abuse Telemetry Heartbeat
- `gep/anti_abuse_telemetry.py`: `build_heartbeat_anti_abuse()` — privacy-preserving
  envelope with HMAC-pseudonymized device/workspace hashes, source-confidence
  labels (hub_required/hub_service/hub_observed), integrity hashes, task timing.
- `config.py`: `ANTI_ABUSE_TELEMETRY_MODE` (default `heartbeat`, explicit opt-out).
- `proxy/lifecycle/manager.py`: heartbeat `meta.anti_abuse` injection when mode=heartbeat.

### Gap 5: Outcome Report Mode (P4-a Slice B)
- `config.py`: `OUTCOME_REPORT_MODE` (default `off`) + `outcome_report_mode()`
  resolver (on/enforce/true → `on`).

### Gap 6: Force-Update from Heartbeat
- `proxy/lifecycle/manager.py`: `_maybe_trigger_force_update_from_heartbeat()` with
  `EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS` (default 5min) — prevents Hub from
  hot-spinning force-updates on every heartbeat.

### Gap 7: Last-Update Ack
- `proxy/lifecycle/manager.py`: `read_pending_last_update()` / `set_pending_last_update()`;
  heartbeat carries `last_update_ack` + `node_secret_version` in payload.

### Stats
- **Tests**: 1573 → **1609** (+36 new tests, 0 regressions)
- **Baseline**: tracking v1.89.11 → **v1.89.14** parity on lifecycle + GEP selection

## [Unreleased] — Sprint 0-8 catch-up against evolver v1.89.11

### Sprint 0: Engineering baseline
- Fixed `gep/sanitize.py` `import json` position bug (was at file bottom, caused NameError).
- `gep/sanitize.py`: reverse leak scan now skips path/URL-shaped env values (#568).
- Added 6 credential redaction patterns (jwt, aws, github, slack, connection_string, high_entropy).
- `CHANGELOG.md` upgraded from stub to Keep-a-Changelog format.
- `CONTRIBUTING.md`: conventional commits with scope; baseline updated to 1331→1534 tests.

### Sprint 1: IDE runtime hooks
- Rewrote `adapters/scripts/runtime_paths.py` (24→315 lines): host-env project dir resolution,
  workspace-id atomic create with symlink guards, FS-only fallback.
- Rewrote `session_start.py` (41→211): workspace-scoped memory recall, non-git notice (throttled),
  dedup, lazy memory read from newest end.
- Rewrote `session_end.py` (48→214): HEAD~1 diff, workspace-id stamping, Cursor systemMessage suppression.
- Rewrote `signal_detect.py` (39→160): context-aware stratification, Claude Code payload parsing,
  multilingual (CJK) fallback.
- New `lock_paths.py` (52 lines): daemon singleton-lock location + lease staleness tunables.
- New `task_recall.py` (103 lines): `@evolver recall` triggered capsule recall.
- Updated `memory_filtering.py`: added `filter_relevant_outcomes` (Node contract).

### Sprint 3: Execution bridge + conversation sniffer
- New `gep/exec_bridge.py` (93 lines): Windows npm .cmd shim resolver (CVE-2024-27980).
- New `gep/conversation_sniffer.py` (240 lines): scan_corpus with local co-occurrence,
  off/shadow/enforce modes, cooldown, CJK support.
- Extended `gep/bridge.py`: added `determine_bridge_enabled()`.
- `evolve/runner.py`: Ralph-loop stale bridge-mode break (#559).

### Sprint 4: Security + seed library + deepening
- Expanded `genes.seed.json` (3→11 genes): full alignment with Node v1.87.0 seed library.
- Rewrote `gep/skill2gep.py` (187→400+): `parse_skill_md` with frontmatter + CJK sections,
  `infer_category` with word-boundary matching, `skill_to_gene_dict` with asset_id + quality heuristics.
- Deepened `gep/idle_scheduler.py` (220→300+): `EVOLVER_IDLE_OVERRIDE`, build-activity detection,
  FS-only idle fallback.
- `gep/schemas/gene.py`: added `avoid` and `_source` (alias) fields.

### Sprint 5: Multi-provider proxy routes
- New `proxy/router/gemini_route.py` (160 lines): Google Gemini API proxy with SSE.
- New `proxy/router/vertex_route.py` (145 lines): Vertex AI proxy with ADC auth.
- New `proxy/router/ollama_route.py` (140 lines): local Ollama proxy.
- New `proxy/router/responses_route.py` (150 lines): OpenAI-compatible API proxy.
- New `proxy/router/models_route.py` (85 lines): `/v1/models` aggregator.
- New `proxy/server/settings.py` (62 lines): proxy settings persistence.
- New `proxy/trace/extractor.py` (65 lines): multi-format token usage extraction.
- New `proxy/trace/usage.py` (60 lines): usage aggregator singleton.
- New `proxy/envelope.py` (45 lines): structured message envelope.
- New `proxy/inject.py` (50 lines): context injection + internal field stripping.
- Updated `model_router.py`: 5-provider upstream detection.

### Sprint 6: ATP CLI + mailbox transport
- Rewrote `atp/cli.py` (86→270): 15 subcommands (buy/orders/tasks/claim/deliver/settle/dispute/publish/policy/proofs/tier/order/status/enable/disable).
- Deepened `atp/atp_execute.py` (87→230): sandbox validation, structured proof building.
- Deepened `atp/atp_task_pickup.py` (99→200): ROI scoring, capability matching, concurrent limit.
- New `gep/mailbox_transport.py` (115 lines): proxy mailbox client with auto-start.

### Sprint 7: Missing modules
- New `gep/token_savings.py` (120 lines): token/USD cost savings tracker with monthly reports.
- New `gep/narrative_memory.py` (85 lines): evolution history narrative compressor.
- New `gep/memory_graph_adapter.py` (120 lines): advanced queries (success trajectory, failure clustering, fuzzy match).
- New `gep/directory_client.py` (75 lines): EvoMap directory service client.
- New `gep/oauth_login.py` (115 lines): OAuth 2.0 device-code flow with keychain integration.
- New `gep/claim_nudge.py` (75 lines): throttled task-claim suggestion generator.
- New `gep/device_id.py` (85 lines): cross-platform anonymous hardware fingerprint.
- New `gep/anti_abuse_telemetry.py` (120 lines): abuse pattern detector (flood/bypass/exhaustion).

### Sprint 8: Experiment framework + i18n + docs
- New `experiment/` module (4 files): agent_runner, metrics, comparison, cli — controlled A/B evaluation.
- New `README.ja-JP.md`: Japanese README.
- New `README.ko-KR.md`: Korean README.

### Stats
- **Tests**: 1331 → 1546+ (215+ new tests, 0 regressions)
- **Source files**: 192 → 217+ (25+ new modules)
- **Seed genes**: 3 → 11
- **Proxy routes**: 4 → 9
- **ATP subcommands**: 5 → 15
- **mypy strict**: 0 errors across all files
- **Baseline comparison**: v1.89.2 → tracking v1.89.11

## [1.89.2] - 2026-06-09

- Initial Python port release tracking Node.js v1.89.2.
- GEP data layer, evolution pipeline, Proxy infrastructure, ATP marketplace (partial),
  IDE adapters (partial), WebUI (partial).

[Unreleased]: https://github.com/EvoMap/evolver/compare/v1.93.0...HEAD
[1.93.0]: https://github.com/EvoMap/evolver/releases/tag/v1.93.0
