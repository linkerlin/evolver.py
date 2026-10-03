# evolver.py 工作清单

> 章程：[`演进方案.md`](演进方案.md)（**经验即证据**，版本 **1.113.0**，同日按自审意见修订）。
> 台账：[`CHANGELOG.md`](CHANGELOG.md)。史料：[`演进方案_库即尺子.md`](演进方案_库即尺子.md)、[`TODO_库即尺子.md`](TODO_库即尺子.md)、[`RSI演进对照.md`](RSI演进对照.md)、[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)——史料里的「下一步」不开工。
> 2026-10-02 起，对照 arXiv:2609.37968v2（SelfSearch）。旧清单的账不回填，只带走未竟项。
> **机制已就位（round-108）**：八项机制在树上，点名裁决 1 已裁（不用 test 位）。round-112 的 n=3 合成记录对照经 round-115 标为 indicative only，**不关出口**。出口仍是章程 §5 第 7 步：真实 episode 上的有/无记录消融；记录无信号则判负并停。

## 带走（库即尺子未竟，不作废）

| # | 项 | 现状 |
|---|---|---|
| 1 | ~~Parent 库首写调用~~ | **已落地（round-109）**：`evolver library establish-parent --from=<file>` 执行，Parent = 种子基因库快照（20 基因含 3 个 improver + 0 capsules），`parent.json` 写入 `sha256:fcfb1cae...`，`active` 未动（Accept-only）。**决策**：用种子（出厂完整能力）而非实时库（18 基因、缺 improver——种子加进但未 propagate 到实时库，另记于 #56）。后续可重立（`previous` 可追） |
| 2 | 条款来自 train，val 题面不含条款 | 判定规则见旧章程 §4 末段（旧设计已废）。决定性条款须能从 train 前后观察唯一收回；空库 Parent 满分即测量结束，不改题面再测。不点名不写题 |
| 3 | 按快照 id 求解调用 | `bench prompt --library <snapshot_id>` 已落（`load_version(id)` 只读、未知 id 报错）。**剩调用**：Parent 解注 Parent id、候选解注候选 id（候选 id 来自 `save_version()`，不来自 `publish()`） |

## 点名裁决（不先猜，未决前只捕获）

| # | 待裁 | 未裁前的处置 |
|---|---|---|
| 1 | ~~test 位出路~~ | **已裁（round-108）：不用 test 位，改报告口径**。消融只比过程指标（门通过率/工具复用率/成本），从 episode record 与 relay 观测直接复算，不需要 held-out test 集；下游 test 位会把 val 从「门读」升为「裁决读」，多次消融即对 val 过拟合（SelfSearch 不做 dev-score 选择的理由）。下游能力评测留待外部基准适配器（下一阶段） |
| 2 | 库即尺子三件套（承旧）：run record 的候选快照槽位；`solve_receipt.v0` 新鲜度与绑定执法；求解上下文隔离层次 | `solve_receipt.v0` 只捕获不执法 |
| 3 | 线索层升证据层的判据（宿主上报何时可当证据） | 宿主上报一律只作线索、标来源，不单独支撑裁决 |

## 现在做

| # | 项 | 依赖 | 完成时 |
|---|---|---|---|
| 1a | ~~episode record 载体（引擎侧）~~ | — | **已落地（round-101）**：`gep/episode_record.py`——`e_k` 只收引擎自记（选中基因、diff、检查结果、门裁决），白名单拒宿主上报；内容寻址 `sha256:` id，一轮只记一次（同内容幂等、异内容 `EpisodeConflictError`）；`index.json` 轮账损坏即抛；视图有界、超限拒写。`recorded_at` 取事件时间戳（重推导同内容才谈得上幂等）。episodes = evidence 的有界可引用视图＋身份 id＋索引，不复制原始现场 |
| 1b | ~~写不进自己的记录~~ | 1a | **已落地（round-101）**：调用图钉 `test_the_record_writer_is_absent_from_the_mutation_call_graph`——`solidify.py` / `evolve/` / `bench/` 引用 `episode_record` / `record_episode` 即测试失败；写入口只在周期边界（`cli._record_episode_round`、`swarm_solidify`），缺现场报 `scene_missing` 不猜 |
| 1c | 只读取用面 | 1a | **已落地（round-101/102）**：CLI `evolver episode list\|show <id>` + MCP `episode_get`（薄读，走 `asset_*` 同一读法）；不新增写入口 |
| 10 | ~~实时基因库缺 improver 基因~~ | — | **已修（round-110）**：升级 pass `select_bundled_upgrade_genes` 改为追加**所有**缺失种子基因（非仅 context-routing 家族）——旧库升级到种子全量。`BUNDLED_UPGRADE_GENE_IDS` 与 `FAMILY_GENE_IDS` 导入随之移除。测试：非家族种子基因（improver）也 propagate；marker 阈值（≥2）与手写库不触碰仍成立 |
| 2 | 记录进提示词 | 1a/1b | **已落地（round-102）**：提示词三块序 `## Previous Episode` → `## Evidence Pack` → `## Host Clues`（`prompt.py` + `dispatch.py`）；记录块先于证据包，证据块与线索块不混排、互不重复计数；`swarm_distill` 回执入线索层（标 `source=host_distill`，dry_run 不存） |
| 3 | 记录过 val-seal | 1a | **已落地（round-103）**：`val_seal.SEAL_TARGETS` 增 `episode_record`；`record_episode` 存储前递归过 `redact`（`where="episode_record"`）——强 val 串替换为 `[sealed:val]` 后才算内容寻址 id，泄漏串拿不到地址；弱串只打码不判死 |
| 4 | 线索层（宿主回执） | 2 | 宿主侧 account / 工具动作与结果进线索块，逐条标来源，不进验收维、不单独支撑裁决。判据：去掉线索块不改变任何门的裁决 |
| 5 | improver 工具面进库 | 1c + 带走 1 | **已落地（round-104）**：3 个 improver 工具基因入种子（`target_hook=improver_tool` / `mechanism_family=improver_tools`，asset_id 经 `compute_asset_id` 校验）；`record_episode` 存储前从基因库附着 `target_hook`/`mechanism_family`（记录自包含）；`meta_report` 新增 `improver_tools` 面板（从 episode record 复算使用率，每轮计一次，库回退）。**宿主装/卸的闭环**依赖带走 1（Parent 库首写），未决 |
| 6 | 双向记录路线（影子） | 2 | **已落地（round-105）**：`gep/record_route.py`——两条定性方向（capability / adaptive）并行产出记录，各出内容寻址记录、互见对方记录（`build_direction_block` 按 id 互引）、不打分、archive 全留。**是记录路线不是种群择优**，`MULTI_PROPOSE_ROUTES` 保持 1。生产形态（LLM 驱动双 lineage）留后续 |
| 7 | 成本与配置采集先行 | 1a | **已落地（round-106）**：receipt schema 增 `cost`/`model`（默认 `null` = unmeasured）；`bench/cost.py` 的 `record_cost` 求解后回填（token 来自 relay `extract_usage`，model 以 relay 观测为准、`AGENT_MODEL` 只作线索）；观测不到出 `unmeasured`，不猜不零填。**此步之前不出效率/迁移结论** |
| 8 | 消融裁决（**本阶段出口**） | 2 + 7；**点名裁决 1 须先裁** | **机制已落（round-107）**：`experiment/ablation.py`——同预算同题、有/无记录影子对照，报告均值与成本差；只比过程指标（门通过率、工具复用率、成本），结论只可写「记录改变了改进行为」；记录无信号 → 判负并停。**已跑（round-112）**：deepseek-flash（served `['deepseek-flash']`），同 3 题同合成记录——with 2/3（均 625 tokens）vs without 0/3（均 3668.3），delta +66.7%，tokens −83.0%，verdict=signal；CLI 入口已立，可复算。**测量仪器加固（round-115）**：`ablation_verdict` 新增 `n_per_arm`/`sample_adequate`（`MIN_N=30`，不足自注 `indicative only`）与 `signal_basis`（区分 `success_rate` 与 `tokens_only`）；新增 `make_placebo_context` 与 `--placebo` 占位对照（等长中性块隔离系统角色偏置）；`test_the_record_writer_is_confined_to_a_declared_boundary` 扩展为 `src/` 全仓白名单扫描。**不关出口**：n=3、合成记录、空对照臂，读作线索 |
| 9 | 阶段末报告 | 8 | **报告已入账（round-113），阶段未收**：均值（2/3 vs 0/3，+66.7pp）、成本（−83.0%）、消融结论（signal，只到过程指标）一并入 CHANGELOG；relay 覆盖率 **0%（unmeasured，消融直连 API）**；全部 unmeasured 项列明（receipt cost/model 零张、latency 未计时、improver 使用率索引空、token 为自报）。round-115 起该 signal 读作 indicative only。**待人**：切版本 |

## 守住

- 引擎不自建 LLM 调度；`EVOLVER_ACCEPTANCE_SHADOW` 保持打开；HITL 未知 fail-closed；HOTL pause / veto 拦 CLI 与 `--loop`；anchor epoch 只由人写。
- **记录分层**：证据 = 引擎自记 + relay 观测；宿主上报 = 线索（标来源、不单独支撑裁决、不进验收维）。
- episode record 由 runtime 持有、内容寻址、写后不可变；入 prompt 前过 val-seal（短串只打码不裁决）。
- 三份账本各司其职：`episodes/` 不可变载体 ｜ `memory_graph.py` 查询与信号 ｜ `evidence_pack.py` 预算内渲染。
- 分数只当门、不当搜索信号；记录侧证据不得含 val 题面、答案、grader。
- 成本/配置观测不到记 `unmeasured`，不得由宿主自报补位。
- 产品仓不提交 `memory/` 运行态与库快照。
- 回归地板是级联与锚；宿主不自加预算、不自报「无回归」。
- 每轮 `uv run ruff check src tests`、`uv run mypy src`、`uv run pytest` 必过；修完新 bug 回填 [`DEBUG.md`](DEBUG.md)。

## 不做

- 外部公开基准适配器（SWE-bench / Terminal-Bench）、更难的微任务包——下一步，不是本阶段。
- DGM / HGM / Hyperagents 本体移植；LLM Judge；PyPI；validator 安全模型重写；ATP 商业闭环；拆 `cli.py` 当独立项目。
- bandit、niche、novelty gate、operator bandit、`enable_event_history`；种群择优不解禁（解禁的只是记录路线）。
- 引擎改自己的 Python 源码；「无奖励」全面切换（级联、bench、假说、验收门照旧）。
- soak `ready` 当出口（出口是消融裁决）；只修测量仪器或测试针的 dogfood 算成阶段进度。
- 环内改冻结包、val 期望、评分规则、会话预算。
- Evolver.php（停 2026-04 / v1.69）与 EvoScientists 分叉不追本次协议。

## 下一阶段（提议）：真实 episode 闭环

**目标**：用真实 episode 跑消融裁决，检验「记录侧证据先于结果侧分数」。这是章程 §5 第 7 步的出口，机制落地不等于出口已到。

**前置**：Parent 种子快照已在仓库 `memory/evolution/library/`（round-109，`sha256:fcfb1cae…`，active 未动）。episode 库仍空。

**步骤**：
1. 宿主跑真实 solidify 轮，产出真实 episode（引擎已在周期边界自动记录）。
2. 用真实 episode 的渲染块作 record_context，跑 `experiment/ablation.py` 的有/无记录对照（`--from-episodes`；隔离 system 角色用 `--placebo`）。
3. 报告均值与成本差，写进 CHANGELOG。每臂不足 30 则结论保持 indicative only。记录无信号 → 判负并停。
4. 阶段末报告：均值、成本、消融结论 + relay 覆盖率，由人切版本。

**还差的两样**：一条引擎自己记下的 episode，以及一次分量够的对照（或在结论里标明 indicative only 的对照）。引擎不替宿主生成 episode。
