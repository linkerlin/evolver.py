# evolver.py 工作清单

> 章程：[`演进方案.md`](演进方案.md)（**经验即证据**，版本 **1.113.0**，同日按自审意见修订）。
> 台账：[`CHANGELOG.md`](CHANGELOG.md)。史料：[`演进方案_库即尺子.md`](演进方案_库即尺子.md)、[`TODO_库即尺子.md`](TODO_库即尺子.md)、[`RSI演进对照.md`](RSI演进对照.md)、[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)——史料里的「下一步」不开工。
> 2026-10-02 起，对照 arXiv:2609.37968v2（SelfSearch）。旧清单的账不回填，只带走未竟项。
> **机制已就位，出口未关。** 点名裁决 1 已裁（不用 test 位）。分量口径（2026-10-03）：证据是一条引擎记下的结算，加上一次 `--from-episodes --placebo` 对照。每臂 n < 30 时 signal 与 no_signal 都只写 indicative only，不切版本，也不判阶段失败。n ≥ 30 且无信号才判负并停。不为凑 30 造题。失败结算与成功结算同一形状，仍只在周期边界记。
> VISTA 机械套具（不替换本阶段出口，不改验收门）：[`VISTA演进方案.md`](VISTA演进方案.md) 的落地清单在 [`TODO_VISTA.md`](TODO_VISTA.md)。

## 带走（库即尺子未竟，不作废）

| # | 项 | 现状 |
|---|---|---|
| 1 | ~~Parent 库首写调用~~ | **已落地（round-109）**：`evolver library establish-parent --from=<file>` 执行，Parent = 种子基因库快照（20 基因含 3 个 improver + 0 capsules），`parent.json` 写入 `sha256:fcfb1cae...`，`active` 未动（Accept-only）。**决策**：用种子（出厂完整能力）而非实时库（18 基因、缺 improver——种子加进但未 propagate 到实时库，另记于 #56）。后续可重立（`previous` 可追） |
| 2 | 条款来自 train，val 题面不含条款 | 判定规则见旧章程 §4 末段（旧设计已废）。决定性条款须能从 train 前后观察唯一收回；空库 Parent 满分即测量结束，不改题面再测。不点名不写题 |
| 3 | 按快照 id 求解调用 | `bench prompt --library <snapshot_id>` 已落（`load_version(id)` 只读、未知 id 报错）。**剩调用**：Parent 解注 Parent id、候选解注候选 id（候选 id 来自 `save_version()`，不来自 `publish()`） |

## 点名裁决（不先猜，未决前只捕获）

| # | 待裁 | 未裁前的处置 |
|---|---|---|
| 1 | ~~test 位出路~~ | **已裁（round-108）：不用 test 位，改报告口径**。消融只比代码真测的过程指标（成功率与 token；门通过率与工具复用率未测），从 episode record 与 relay 观测直接复算，不需要 held-out test 集；下游 test 位会把 val 从「门读」升为「裁决读」，多次消融即对 val 过拟合（SelfSearch 不做 dev-score 选择的理由）。下游能力评测留待外部基准适配器（下一阶段） |
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
| 4 | ~~线索层（宿主回执）~~ | 2 | **已落地（round-102 收录、round-117 钉判据）**：宿主回执入线索块（`swarm_distill` → `episode_clue.append_clue`，标 `source=host_distill`，dry_run 不存）；渲染进提示词 `## Host Clues`（1200 字预算，工作草稿尾注其后），逐条标来源、不进验收维。判据「去掉线索块不改变任何门的裁决」由机器钉执守：`test_clue_layer_never_feeds_a_gate_verdict` 扫描全部结算/门模块（solidify / hypothesis / policy_check / llm_review / anchor / frozen_gate / regression_guard / compare / ablation 族），引用线索层即测试失败 |
| 5 | improver 工具面进库 | 1c + 带走 1 | **已落地（round-104）**：3 个 improver 工具基因入种子（`target_hook=improver_tool` / `mechanism_family=improver_tools`，asset_id 经 `compute_asset_id` 校验）；`record_episode` 存储前从基因库附着 `target_hook`/`mechanism_family`（记录自包含）；`meta_report` 新增 `improver_tools` 面板（从 episode record 复算使用率，每轮计一次，库回退）。**宿主装/卸的闭环**依赖带走 1（Parent 库首写），未决 |
| 6 | 双向记录路线（影子） | 2 | **已落地（round-105）**：`gep/record_route.py`——两条定性方向（capability / adaptive）并行产出记录，各出内容寻址记录、互见对方记录（`build_direction_block` 按 id 互引）、不打分、archive 全留。**是记录路线不是种群择优**，`MULTI_PROPOSE_ROUTES` 保持 1。生产形态（LLM 驱动双 lineage）留后续 |
| 7 | 成本与配置采集先行 | 1a | **已落地（round-106）**：receipt schema 增 `cost`/`model`（默认 `null` = unmeasured）；`bench/cost.py` 的 `record_cost` 求解后回填（token 来自 relay `extract_usage`，model 以 relay 观测为准、`AGENT_MODEL` 只作线索）；观测不到出 `unmeasured`，不猜不零填。**此步之前不出效率/迁移结论** |
| 8 | 消融裁决（**本阶段出口**） | 2 + 7；**点名裁决 1 须先裁** | **机制已落（round-107）**：`experiment/ablation.py`——同预算同题、有/无记录影子对照，报告均值与成本差；只比代码真测的成功率与 token（门通过率、工具复用率未测），结论只可写「记录改变了改进行为」。n < 30 的 signal 与 no_signal 都只写 indicative only，不判阶段失败；n ≥ 30 且无信号才判负并停。**已跑（round-112）**：deepseek-flash（served `['deepseek-flash']`），同 3 题同合成记录——with 2/3（均 625 tokens）vs without 0/3（均 3668.3），delta +66.7%，tokens −83.0%，verdict=signal；CLI 入口已立，可复算。**测量仪器加固（round-115）**：`ablation_verdict` 新增 `n_per_arm`/`sample_adequate`（`MIN_N=30`，不足自注 `indicative only`）与 `signal_basis`（区分 `success_rate` 与 `tokens_only`）；新增 `make_placebo_context` 与 `--placebo` 占位对照（等长中性块隔离系统角色偏置）；`test_the_record_writer_is_confined_to_a_declared_boundary` 扩展为 `src/` 全仓白名单扫描。**阶段出口机器契约（本轮，仪器修补）**：`--stage-exit`——种子 AB/BA 交错、逐调用记录（延迟/三段 tokens/错误类/served model 全计时）、逐题配对精确检验、采样冻结 + 服务端 prompt 失衡度量；真实 episode + placebo + 唯一任务 + 已知 commit + `--output` 落盘，五缺一 exit 2；38 测试钉住，活体 n=2 烟雾 `eligible/inconclusive`（数字在 CHANGELOG）。**不关出口**：n=3、合成记录、空对照臂，读作线索 |
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

## 本阶段出口（不是下一阶段）

外部基准适配器仍在「不做」。下面是 §5 第 7 步。

**口径**：一条引擎记下的结算，加上一次 `--from-episodes --placebo`。n < 30 只写 indicative only，不切版本，也不判阶段失败。n ≥ 30 且无信号才判负并停。机器契约形态走 `--stage-exit`（种子交错/逐调用记录/配对检验/五门 exit 2），旧 `--ablation` 口径不变。

**已接到记录上的结算**：隔离工作区里一次真实 `evolver solidify` 拒绝（`hypothesis_missing`）。回滚前的 diff 在记录里。episode `sha256:ffe36d9e529b728f354e0f5143efae9955551b3583b77775a899234703e1a009`。这不是把 Parent 条拨到 0.0 造出来的 Accept，也不是 soak 宿主轮。运行态在 `C:\Temp\evolver-reject-episode\`，不进产品 git。

**对照**（已跑，不收阶段）：`demo-repair-1` 与 `demo-neutral-1`，n=2，`--from-episodes --placebo`，deepseek-flash。2/2 对 2/2，tokens 553 对 348（+58.9%），`no_signal`，`stage_stop=false`，结论 `indicative only`。relay 覆盖率 0%。数字在 CHANGELOG。版本保持 **1.113.0**。

**最强对照（R6，2026-10-18，仍 indicative）**：真实 MCP 闭环先产出带截断锚点与 `prediction_delta` 的 episode（`sha256:23c67dce…`），再在去饱和对称题包 `tasks_grounded.json`（6 过程决策 + 2 对照，n=8，digest 入账、选项对称不泄题）上跑两次 `--stage-exit --from-episodes --placebo`（`--order-seed 7`/`13`）：两批均 with_records 8/8 对 without 2/8，配对 `p=0.03125`、`eligible=True`、`paired=a_better`；n=8 < 30 → `stage=inconclusive`，只记 indicative only，不收阶段。出口仍卡「合法的 ≥30 题来源」，下一阶段提议见文末。

**P0 人裁（已决，执行中）**：feedback 自报维持现状并修章程（§4/§6.3 已补转向-结算区分）；episode 产地定为 MCP 闭环——DeepSeek 宿主活体全结算已通（`validation_failed` 拒绝轮入 episode），结算半环钉进 Tier B，数字在 CHANGELOG。

## 下一阶段（提议，待人裁）：外部尺子与真实闭环

> 2026-10-22 由 agent 起草（round-116 文档轮），尚未经人裁。人裁之前的默认：不开工；本节不构成排期。点名裁决 2（solve_receipt 执法）、3（线索层升证据判据）仍由人持，本提议不代答。

**判断**：「经验即证据」的**机制面**已全部就位——记录（写后不可变＋调用图钉）→ 打码（val-seal）→ 提示词（三块序）→ 重注视（episode_inspect）→ 预期落差（prediction_delta）→ 消融机器契约（`--stage-exit` 五门）；VISTA 套具补齐了过程侧可用性；治理面（HITL/HOTL/anchor/级联/假说门）领先对照对象。剩下的缺口全部在**证据面**：真实 episode 只有个位数结算；所有对照 n < 30 只能 indicative；relay 覆盖率 0%（token/latency/模型全靠自报）；效率与迁移维无测量面。章程自己已两处把下一步指向外部基准（点名裁决 1 的「下游能力评测留待外部基准适配器」、§7 的「这是下一步，不是本阶段」）——本提议把这条线接起来。

**目标**：先用合法的 ≥30 题把本阶段出口关上；再用同一批外部尺子承接下游能力读数，把效率/迁移维从 `unmeasured` 变成可测。机制不再新增，新增的只有运行与尺子。

**步骤**：

1. **真实 episode 规模化**（不改章程即可做）：soak / 仓外沙盒里用 MCP 闭环跑多轮真实配对会话，积累成功与拒绝同形状的结算，目标 ≥30 条。引擎不造题、不代跑；产出归运行态不进产品 git。
2. **合法题源（须人裁其一）**：(a) 从真实结算派生对称过程决策题——R6 方法的规模化（选项对称、题干不泄密、digest + commit 冻结入账），前提是人裁「从引擎记录派生不算造题」并定题面纪律；(b) 人点名一份外部基准任务集当题源。两条路 `--stage-exit` 五门都不变。
3. **出口裁决**：n ≥ 30 的 `--stage-exit --from-episodes --placebo`。signal → 人切版本收阶段；无信号 → 判负并停（章程口径原样）。relay 观测转正可与 1 并行（求解/消融经本地代理记账，token/latency/model 从自报升为观测；属仪器修补，不计阶段进度）。
4. **外部基准适配器（新阶段主体）**：SWE-bench Verified 子集 / Terminal-Bench 适配器，仓外冻结（对齐 anchor 的「验证面在环外」）。先只做**能力读数**（承接点名裁决 1 的留位），不进任何门、不当搜索信号；「更难的微任务包」由此获得合法来源。
5. **效率/迁移维在此之后才有结论**：SelfSearch 的 −38.5% 共享题成本与跨模型族迁移，在 relay 覆盖与外部读数就位前一律保持 `unmeasured` 书写。

**为什么是这个顺序**：出口（1–3）不需要新机制，只需要真实运行——引擎无法自主产出真实 episode，这正是 round-108 把它列为下一阶段入口的原因；外部适配器（4）既承接已裁的留位，又不碰任何门；relay（3 并行）是所有效率主张的前置。三者都不解禁种群择优、都不让引擎改自己的源码、都不动冻结包与验收门。

**不做**（沿章程）：不为凑 30 造题；外部基准只当尺子不当信号；不移植 DGM/HGM 本体；不在此阶段内同时开两条战线——出口未关之前，适配器不开工。

> **2026-10-22 会话实录**：两项裁决（题源 ①、战役 ②）已当面问过、未获作答——按默认保守，不开工，全量战役与题面派生均未启动。试点数据已采：Tier B `test_live_host_settles_a_round_into_episodes` 单轮真实结算 **11.7 秒 / API 成本美分级**（tick→DeepSeek 决策→应用编辑→distill→hypothesis→solidify→episode 落库，`1 passed in 11.72s`）。据此 ≥30 条结算的战役量级约十分钟、成本可忽略——裁 ② 的实际风险只剩「要不要现在动 API」本身。①+② 落笔即执行。
