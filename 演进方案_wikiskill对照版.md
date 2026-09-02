# evolver.py 演进方案（wikiskill 对照审计版）

> **编制日期**：2026-09-01
> **对照基准**：`C:\GitHub\wikiskill`（GitHub: ashutoshsinghpr7/wikiskill v0.1.3，MIT，arXiv:2608.27454 之忠实实现）
> **本仓库基线**：`pyproject.toml` 1.95.0，HEAD `72891ea`，300 源文件 / 51,645 LOC / 274 测试文件 / 3,129 用例
> **与现有文档之关系**：本文承接《演进方案.md》主线 B（§13 方法论审计），为其提供一面具体镜子与可执行落地路线。原《演进方案.md》继续作为 parity 审计与 Sprint 回执之单一真相源，本文不改写之，只补充「向 wikiskill 学什么、怎么学」。

---

## 0. 执行摘要

两个项目都在做「AI agent 技能自进化」，但走的是两条相反的路：

| 维度 | evolver.py | wikiskill |
|---|---|---|
| 出身 | 对重度混淆 Node 商业引擎的行为等价移植 + 文献驱动概念收割 | 对一篇论文（Algorithm 1）的忠实落地 |
| 规模 | 300 文件 / 51,645 LOC / 14 运行时依赖 / ~196 环境变量 / 26 个三层 flag | 17 文件 / 2,093 LOC / **0 运行时依赖** / 个位数常量 |
| 进化单元 | Gene（信号→变异策略）+ Capsule + Recipe + 种子基因 17 个 | 单一 SKILL.md 技能文档，S₀=∅ 从零长出 |
| 适应度 | **默认假**：成功事件 score 硬编码 1.0（`gep/solidify.py:708`），真级联在 flag 后（`enable_fitness_cascade` 默认 off） | **永远是真**：train/val 分割的自动评分基准，严格 `R_val > R_best` 才接受（`gating.py:5`） |
| 知识层 | LESSONS_LEARNED + memory_graph + 事件账，与技能状态混杂于 `.evolver/` | 独立 wiki 层（markdown + 独立 git 仓），**永不回滚**，技能回滚不影响知识 |
| 变异执行 | 打印提示词给外部 agent 自由改码，事后 `solidify` 验证 | agent 只写提案 JSON，harness 机械应用 + 文本锚点硬校验（`gating.py:67-104`） |
| 被拒记忆 | `failed_capsules.json` + `enable_lineage_lessons`（默认 off） | 被拒提案全文嵌入 `wiki/skill-impact.md`，主路径，proposer 必读 |
| 统计判定 | `experiment/` 有 z 检验/Wald CI 但**未挂主 CLI**（原演进方案 §3.2 自认） | `compare` 命令：配对精确二项检验，纯手写（零依赖） |
| 诚实性工程 | 爆炸半径、内容寻址、脱敏（强） | 不可变轨迹、幻影评分防御、启动失败检测、负面结果公开（`docs/RUNS.md`） |
| 产品化 | 未发布，依赖 uv 本地跑 | PyPI（OIDC 无 token 发布）+ CI 三版本矩阵 + mkdocs 站 + cron 夜间进化 |

**一句话判断**：evolver.py 的工程素养（账本、内容寻址、blast radius、测试纪律）高于 wikiskill；但 wikiskill 在**进化算法的三件根本事——可测适应度、知识/技能分离、诚实性工程**上全面领先，且这三件事恰好是《演进方案.md》§13 自曝的最大缺口。wikiskill 用 2,093 行把 evolver.py 用 26 个 flag 承诺的事做成了主路径。

**演进总纲**（六个阶段，详见 §5）：

1. **S25 冻结**：停止 parity 追逐，把「方法论主线」升为唯一主线；
2. **S26 适应度革命**（P0）：内置自动评分基准 + fitness cascade 转默认 + 严格门控；
3. **S27 知识层独立**（P1）：wiki 化活记忆，知识永不回滚，被拒记忆主路径化；
4. **S28 轨迹诚实**（P1）：不可变轨迹仓 + 启动失败检测 + 评估前沙箱重建；
5. **S29 提案化变异**（P2）：外部 agent 从「自由改码」改「提交提案」，solidify 机械应用；
6. **S30 判定与瘦身**（P2）：配对统计判定挂主 CLI + 跨后端迁移 + 配置面/依赖/flag 三层减负。

---

## 1. 设计思想对比

### 1.1 出身决定形态

**evolver.py** 是一部移植史。每个源文件的 docstring 第一行都是 "Equivalent to Node's X.js"；为了保留「Node 镜像风格」，`pyproject.toml:87-102` 全局豁免了 12 条 ruff 规则（多分支/多返回/多参数/惰性导入……），并注释承认「重新启用需审计所有出现处」。**移植保真度压倒了设计自主性**。此后 24 个 Sprint 每个都往上加一层概念（epigenetics、autopoiesis、niche、UCB1、新颖性门、验收门、因果诊断、多提议者、轨迹导出、ATP、Recipe、MCP、工作流 DSL、personality v2……），靠 flag 隔离而非吸收——这是「追加而非整合」的演进方式。

**wikiskill** 是一篇论文的可执行化。`harness.py:1-13` 的模块 docstring 直接写 Algorithm 1 伪代码；采样策略标注 "per Appendix C"（`harness.py:52`）；三个角色的提示词标注 "adapted from Appendix E"（`prompts.py:1-6`）；CONTRIBUTING.md 明文 *"algorithm fidelity matters more than code churn"*。它没有发明任何概念，只把一个循环做透。

**教训**：evolver.py 不缺概念，缺的是「一个被测量证明有效的循环」。概念数量与进化效果之间没有因果关系；被门控接受的技能数量才有。

### 1.2 知识/技能分离与不对称回滚

wikiskill 的核心不变式（`README.md:24`）：**知识永不回滚，技能必须过门控**。

- 技能是「假设」，可撤销：拒绝即 `git reset --hard`（`gating.py:107-110`）；
- 知识是「证据」，只累积：wiki 是独立 git 仓，每次维护与每次门控后都做审计提交（`wiki.py:23-30`，注释 *"knowledge is never rolled back, but every change is recorded"*）。

evolver.py 的知识散布在 `LESSONS_LEARNED.md`、`memory_graph.jsonl`、`events.jsonl`、`autopoiesis_rules.json`、`failed_capsules.json` 五处，全部混在 `.evolver/`/`memory/` 运行时状态里，随 rollback 模式（`EVOLVER_ROLLBACK_MODE=stash`）可能被一并 stash。**知识与技能没有独立的生命周期**——一次坏回滚可能把教训也回滚掉。

### 1.3 适应度：测量出来的，还是声明出来的

这是两个项目最本质的分野。

**wikiskill 的适应度是测量**：22 个确定性任务（13 train / 9 val，`bench.py`，seed=42 可复现），四类自动评分器（`exact`/`contains`/`json_field`/`code_stdout`，`scoring.py`，文件缺失一律 0 分不崩溃），每次评估前强制重建干净沙箱（`gating.py:144-150`）。接受条件只有一条：`R_val > R_best`（严格大于，`gating.py:5`）。基准自身还有自洽性测试——把期望答案写回沙箱，评分器必须给 1.0（`test_core.py:100-115`）。

**evolver.py 的适应度是声明**：默认路径下 `mutation.validation` 为空，验证通过即 `score: 1.0`（`solidify.py:708`）——「自然选择」一环在默认配置下名存实亡。真正的测量手段（ruff→mypy→pytest 级联、T0 冻结验收门、UCB1 选择）全部存在，但全部默认关闭：

| 机制 | 位置 | 默认 |
|---|---|---|
| 定量适应度级联 | `enable_fitness_cascade` | **off**（`feature_flags.py:62`） |
| 验收门（T0 冻结测试通过率 × N 重复） | `enable_acceptance_gate` | **off**（`feature_flags.py:52`） |
| 谱系教训（被拒基因沿袭注入提示词） | `enable_lineage_lessons` | **off**（`feature_flags.py:71`） |
| 新颖性门（拒绝近重复变异） | `enable_novelty_gate` | **off**（`feature_flags.py:74`） |
| UCB1 选择采样 | `enable_bandit_selection` | **off**（`feature_flags.py:65`） |
| niche top-k 档案 | `enable_niche_topk` | **off**（`feature_flags.py:68`） |

这些机制是 Sprint 22–23 依据同一批文献（GEPA/AlphaEvolve/ShinkaEvolve/MAP-Elites）建起来的，方向与 wikiskill 完全一致——**问题不是没有，而是永远在 flag 后面**。wikiskill 证明了同样的机制可以作为唯一路径稳定运行。

### 1.4 诚实性工程

wikiskill 把「不作弊」做成了架构约束，每条都对应一次真实事故：

| 机制 | 位置 | 防什么 |
|---|---|---|
| 轨迹不可变：已存在即抛 `FileExistsError` | `traces.py:27-41` | 事后篡改/覆盖证据 |
| 评估前强制重建沙箱（删除规格外文件） | `gating.py:144-150` + `tasks.py:80-104` | 幻影评分（评到上次实验的残留产物）——Run 4 整个作废的根因 |
| 零工具调用 = 启动失败检测 | `gating.py:127-134` | 死会话被当成行为证据 |
| 被拒提案全文保留 | `prompts.py:123-142` | proposer 重复已失败的尝试 |
| 负面结果公开 | `docs/RUNS.md` | 自我欺骗；"live acceptance 至今未发生"被明确列为未解决的科学问题（README:199） |
| 陷阱任务生成时断言 bug 不自抵消 | `bench.py:411` | 基准本身有洞 |

evolver.py 有对等素质的机制（爆炸半径先捕获再回滚 `solidify.py:341`、内容寻址 `content_hash.py`、密钥脱敏 `redact.py`、沙箱命令白名单），但**在评估诚实性这一面**没有对应物：轨迹导出（`gep/trajectory/`）是可重建的中间产物而非不可变证据层；没有启动失败检测；`experiment/` 框架甚至还没挂上主 CLI。

### 1.5 表面积哲学

| | evolver.py | wikiskill |
|---|---|---|
| 运行时依赖 | 14（含 **boto3**、keyring、GitPython、mcp） | **0**（手写二项检验 `compare.py:29-40`，subprocess 调 git） |
| CLI 子命令 | 56 个 parser（`cli.py` 1,287 行） | 11 个 |
| 环境变量 | ~196 个 + 80 个顶层常量 | 个位数 |
| 最大文件 | `gep/cli_contracts.py` 1,406 行 | `bench.py` 423 行 |
| 模块切分 | 一个 gep/ 142 文件 | 每模块一个名词（wiki/tasks/traces/scoring/gating/harness/compare/transfer） |

wikiskill 的 CONTRIBUTING.md:20 明文 *"stdlib only (no new dependencies without discussion)"*。零依赖不是洁癖，是**可审计性约束**：依赖越少，门控结论越可信。

### 1.6 agent 的角色：闭环编排 vs 环外提示词

**wikiskill 的循环是闭的**：harness 子进程编排真实 agent（`hermes chat --oneshot` / `claude -p`），学生/维护者/提案者三角色是同一模型的不同 prompt，一轮 `evolve` 从轨迹到判决全自动。每个工作区有隔离的 agent profile（`HERMES_HOME`/`CLAUDE_CONFIG_DIR`），活跃技能集以**符号链接**装载（`hermes.py:66-87`）——门控时 agent 看到的**恰好**是候选技能集，否则门控无意义。

**evolver.py 的循环是开的**：`dispatch` 阶段把 GEP 提示词打印到 stdout 或 `sessions_spawn`（`evolve/pipeline/dispatch.py:202`），等外部 agent 改完代码后跑 `evolver solidify`。`--loop` 无人值守时实际是「提示词生成器 + 等待者」。这意味着：
- 引擎无法独立证明任何一次进化有效；
- 外部 agent 的自由度不受控（直接改码，没有提案边界）。

### 1.7 提案化变更：把 LLM 的自由度关进笼子

wikiskill 最精巧的机制之一：**agent 不直接碰技能文件**。proposer 写一份提案 JSON（create/patch/no_action，`prompts.py:114-117`），harness 的 `apply_proposal`（`gating.py:67-104`）机械执行：

- patch 只有三种操作：`append` / `replace` / `insert_after`；
- `replace`/`insert_after` 找不到 target 文本**直接抛 ValueError**——防 agent 幻觉出补丁；
- 应用前 `commit_base` 快照，拒绝即 `git reset --hard`。

evolver.py 的变异由外部 agent 直接作用于代码库，边界只有 `constraints.max_files`/`forbidden_paths`（基因声明）和事后 blast radius 测量。**事前无结构化提案，事后才知道改了什么**——这就是为什么新颖性门（`_novelty_duplicate_diff:501`）只能在 diff 层面做近似去重，而无法在意图层面判重。

---

## 2. wikiskill 领先点清单（逐项，附证据）

按对本仓库痛点的针对性排序。**标注 ✅ 的表示 evolver.py 已有对应物，差距在「默认关闭/未挂主线/不完整」**。

### L1. 定量适应度闭环（最核心）
- **wikiskill**：内置自动评分基准（22 任务，四类评分器，确定性生成）；接受条件 `R_val > R_best` 是循环的**唯一**判决（`harness.py:158-164`）；`r_best == 1.0` 早停（`harness.py:124-126`）；基线门控先于一切（`harness.py:114-121`）。
- **evolver.py**：✅ 有 `enable_fitness_cascade`（ruff→mypy→pytest 短路级联）与 `enable_acceptance_gate`（T0 冻结通过率 × N 重复，支持影子模式 `gep/acceptance/report.py`）——但全部 flag-off；默认路径 score=1.0。
- **差距性质**：不是能力差距，是**承诺差距**。机制都造好了，没人敢把它变成默认。

### L2. 知识/技能两层分离 + 不对称回滚
- **wikiskill**：wiki 与 skills 是两个独立 git 仓；技能回滚不触碰知识（`test_harness.py:133-149` 专门测这条）；知识只审计不回滚。
- **evolver.py**：知识五处散布（§1.2），与运行时状态同目录，回滚策略（stash/hard）可能殃及。
- **差距性质**：架构缺失。

### L3. 轨迹诚实性三件套
- **wikiskill**：不可变 Raw 层 + 幻影评分防御（强制重建沙箱）+ 启动失败检测（零工具调用）。
- **evolver.py**：`gep/trajectory/` 是多源轨迹**重建**工具（为蒸馏服务），不是证据层；无启动失败检测；评估无沙箱重建概念。
- **差距性质**：架构缺失（部分材料可复用）。

### L4. 提案化变更 + 机械应用 + 锚点校验
- **wikiskill**：提案 JSON 三操作，锚点不中即拒，`no_action` 是合法输出（`harness.py:140-147`）。
- **evolver.py**：✅ 有 `enable_constrained_genes`（约束基因）与 `hooks/ast_merge.py`（AST 级合并约束：拒绝删顶层函数）——但 flag-off，且仍是「agent 改完再验」而非「提案先审后应用」。
- **差距性质**：机制有影子，范式未转变。

### L5. 被拒记忆主路径化
- **wikiskill**：被拒提案全文（JSON + diff）嵌入 `wiki/skill-impact.md`，proposer 的剧本技能强制先读它（`skills/wikiskill-proposer/SKILL.md`），不得重复被拒方案。
- **evolver.py**：✅ 有 `failed_capsules.json`（`asset_store.py:462`）、新颖性指纹（`solidify.py:611-627`）、`enable_lineage_lessons`（Sprint 22.6，GEPA 谱系教训）——但谱系教训 flag-off，且 failed_capsules 注入提示词仅为预览字段（`prompt.py:180`），无「不得重复」的硬约束。
- **差距性质**：机制有，承诺无。

### L6. 配对统计判定
- **wikiskill**：`compare` 命令——同一 val 集各跑 N 次，只算不一致对，双侧精确二项检验（手写，`compare.py:29-40`），`p ≤ 0.05` 且方向正确才判胜；还有「轨迹跨迭代混合」的公平性咨询（`compare.py:86-95`）。
- **evolver.py**：✅ 有 `experiment/`（A/B 对照 + trigger_shift 过拟合评估 + z 检验/Wald CI）——但原演进方案 §3.2 自认「`experiment` 仍未挂主 CLI」。
- **差距性质**：能力在，入口无。

### L7. 评估环境隔离
- **wikiskill**：每工作区独立 `HERMES_HOME`/`CLAUDE_CONFIG_DIR`，捆绑技能 opt-out、空记忆、符号链接装载候选技能集——保证门控时 agent 看到的**恰好**是被评估的技能集。
- **evolver.py**：✅ 有 `--solo` 隔离与 `EVOLVER_SESSION_SCOPE` 每项目隔离，但那是**运行**隔离，不是**评估**隔离；验收门跑在同一个工作区上，无「评估时环境恰好等于候选态」的保证。
- **差距性质**：概念缺失。

### L8. 零依赖与表面积纪律
- **wikiskill**：0 运行时依赖；每个模块一个名词、≤423 行；11 个 CLI 命令。
- **evolver.py**：14 依赖（boto3 出现在一个本地进化引擎里值得审视）、56 个 parser、~196 环境变量、26 个三层 flag。
- **差距性质**：纪律缺失（有历史原因，但须还债）。

### L9. 负面结果公开
- **wikiskill**：`docs/RUNS.md` 逐次记录——Run 4 整个作废、Run 5/6 全是否决与诚实负结果、每次花费（~$0.09/迭代）。「live acceptance 至今未发生」被写进 README 的 Roadmap 作为**未解决的科学问题**。这种诚实本身就是机制有效性的证据（maintainer agent 曾用自己的模式页诊断出宿主框架的幻影评分 bug）。
- **evolver.py**：✅ CHANGELOG/演进方案的自我审计素质很高（§13 自曝适应度缺陷）——但缺一个「逐次运行、逐次判决、可被外人复核」的运行日志面。
- **差距性质**：文化已有，载体缺失。

### L10. 产品化闭环
- **wikiskill**：PyPI（OIDC trusted publishing 无 token）+ CI 三版本矩阵 + mkdocs 文档站 + `hermes cron` 夜间进化（`docs/CRON.md`，含防并发护栏）+ skills tap（蒸馏产物可被 Hermes 直接安装）+ 跨后端迁移命令（`transfer`，同 SKILL.md 格式）。
- **evolver.py**：未发布（README 写 "once published"）；CI 存在但多 OS 仅 advisory；技能生态互通有 `skill2gep.py` 单向入口。
- **差距性质**：发布与生态面落后。

### 同时须承认：evolver.py 的既有优势（不得在演进中丢失）

1. **账本设计**：`events.jsonl` 仅追加 + 内容寻址 `asset_id` + blast radius + 执行轨迹 + 失败也记账（`enable_failure_events`），可审计性超过 wikiskill 的 `state.json` history。
2. **选择器深度**：信号匹配 + 活记忆调制 + 表观遗传抑制 + preferred 加权 + 惰性基因禁用 + 可选 UCB1（`selector.py:162-272`）——wikiskill 没有选择层（每轮只有一个提案）。
3. **安全模型**：内容哈希静默拒载、密钥脱敏、沙箱命令白名单、proxy 默认 127.0.0.1、发布验证闸——信任边界处理远比 wikiskill 完整。
4. **工程闸门**：mypy strict + ruff 全绿（曾清偿 885 存量）+ 3,129 测试 + 原子写 + filelock。
5. **autopoiesis 层**：原演进方案 §13 自评「12 个参照方法无一具备」，是本仓库真正的原创资产，wikiskill 无对应物。
6. **多基因供给管道**：种子/蒸馏/候选生成/Hub 拉取/技能转换五路供给，wikiskill 只有单路（proposer）。

---

## 3. 差距映射总表

| # | wikiskill 机制 | 证据 | evolver.py 现状 | 行动 | 阶段 |
|---|---|---|---|---|---|
| 1 | 自动评分基准（任务+评分器+分割） | `bench.py`/`scoring.py`/`tasks.py` | 无 | 新建 `evolver bench` 子系统 | S26 |
| 2 | 严格门控 `R_val > R_best` | `gating.py:5,158-164` | score=1.0（`solidify.py:708`）；验收门 flag-off | cascade+gate 转默认；引入 r_best 状态 | S26 |
| 3 | train/val 分割防过拟合 | `tasks.py` split 校验 | 无（T0 冻结只测通过率，不分训练/验证） | 基准分割 + 评估只用 val | S26 |
| 4 | wiki 知识层（独立 git 仓，永不回滚） | `wiki.py` | 知识五处散布 | 建 `wiki/` 层，收编 LESSONS_LEARNED/memory_graph 的**人类可读投影** | S27 |
| 5 | 被拒提案全文保留 + 必读约束 | `prompts.py:123-142` + proposer SKILL | lineage_lessons flag-off | 转默认 + 提示词硬约束「不得重复指纹」 | S27 |
| 6 | 轨迹不可变 | `traces.py:27-41` | trajectory/ 是重建器 | 增加只追加证据仓（复用事件账模式） | S28 |
| 7 | 幻影评分防御（沙箱重建） | `gating.py:144-150` | 无 | 评估任务执行器加 force-materialize | S28 |
| 8 | 启动失败检测 | `gating.py:127-134` | 无 | 轨迹入库前零工具调用分类 | S28 |
| 9 | 提案 JSON + 机械应用 + 锚点校验 | `gating.py:67-104` | constrained_genes/ast_merge flag-off | 定义 GeneProposal schema；solidify 增「提案应用」模式 | S29 |
| 10 | no_action 合法化 | `harness.py:140-147` | 无（无信号时靠饱和门跳过周期） | 选择器输出显式 no_mutation 事件 | S29 |
| 11 | 隔离评估 profile | `hermes.py:45-87` | solo/session_scope 是运行隔离 | 验收门支持在干净 worktree/容器评估 | S26+ |
| 12 | 配对二项判定 | `compare.py` | experiment/ 未挂 CLI | `evolver compare` 挂主 CLI，补配对检验 | S30 |
| 13 | 跨后端迁移 | `transfer.py` | skill2gep 单向 | `evolver transfer` + SKILL.md 双向 | S30 |
| 14 | 零依赖纪律 | `pyproject.toml:28` | 14 依赖 | 依赖审计（重点审视 boto3/keyring/GitPython） | S30 |
| 15 | 运行日志公开（含负面） | `docs/RUNS.md` | 无 | `evolver report` 生成逐次判决报告 | S27 |
| 16 | PyPI + 文档站 + cron | release.yml/CRON.md | 未发布 | 发布决策点 | S30 |

---

## 4. 演进总原则（Non-negotiables）

1. **不拆除，只转正**：Sprint 22–24 建的机制全部保留；演进动作是「flag-off → flag-on → 默认 → 唯一路径」四级转正，而非重写。
2. **不触碰 parity 声称**：主线 A 已闭合转维护；本方案的改动一律走新模块或 flag 转正，不修改已对齐的行为面。
3. **每个阶段带验收门**：本方案自己也要过门控——每阶段完成标准是可测的，不接受「已实现」式声明。
4. **测量先于概念**：在 S26（适应度）落地前，冻结一切新概念引入（Sprint 25 起 `概念收割` 暂停）。
5. **诚实优先**：所有负面结果（含「门控连续 N 次否决」）进运行报告，不得静默。

---

## 5. 分阶段演进方案

### S25 — 冻结与基线固定（1 周）

**目标**：停止追逐，把家底量化。

| # | 工作项 | 落点 |
|---|---|---|
| 25.1 | 宣布主线 A（parity）转维护模式，上游新版本只记不追 | 演进方案.md §0 增补决策条目 |
| 25.2 | 冻结概念引入：`概念收割` 暂停，新增实验机制一律先走 S26 的基准证明 | 决策记录 |
| 25.3 | 建立**基线快照**：当前默认配置下跑一遍完整自进化周期，把事件账、score 分布、flag 状态固化为 `baseline-1.95.0/` 参照 | `scripts/baseline_snapshot.py` |
| 25.4 | 依赖审计启动：逐一审视 14 个运行时依赖的去留（boto3 是否可移入可选组？GitPython 可否换 subprocess+git？） | `docs/dependency-audit.md` |
| 25.5 | 环境变量清点：~196 个变量造册，标注「在用/僵尸/重复」，为 S30 合并做准备 | `scripts/env_inventory.py` |

**验收**：基线快照可复现（两次运行事件账 diff 为空集，除时间戳）；审计报告合入。

---

### S26 — 适应度革命（P0，2–3 周）

> 本方案的心脏。目标：让「自然选择」在默认配置下真实发生。

**5.26.1 内置自动评分基准 `evolver bench`**

新建 `src/evolver/bench/`（对标 wikiskill 的 `bench.py`+`tasks.py`+`scoring.py`，但利用本仓库既有设施）：

- **任务格式**：复用 wikiskill 的 `tasks.json` 设计（`{id, split, prompt, sandbox, grader}`）——它已被验证且无依赖。评分器四类照搬语义；`code_stdout` 类复用 `gep/validator/` 沙箱执行器（白名单已就绪）。
- **任务来源**（三层）：
  1. 内置确定性基准（对标其 22 任务，瞄准 agent 经典失败模式）；
  2. **仓库自身任务化**：把 `scripts/validate_modules.py` + pytest 快子集 + ruff/mypy 变成三个「仓库健康任务」——evolver.py 首先拿自己当被进化对象（这正是它已经在做的：`memory/` 与 `.evolver/` 已入仓）；
  3. 用户任务包（`evolver bench import <tasks.json>`，schema 校验对标 `tasks.py:39-55`）。
- **自洽性测试**：期望答案写回沙箱必须得 1.0（对标 `test_core.py:100-115`）。
- **基准生成断言**：任何「陷阱任务」生成时断言缺陷不自抵消（对标 `bench.py:411`）。

**5.26.2 fitness cascade 转默认**

- `enable_fitness_cascade` 默认 **on**：`solidify` 默认验证 = ruff → mypy → pytest 级联（已实现，短路+分级超时就绪）。
- 保留基因自带 `validation` 作为级联**之后**的附加层，不再作为唯一验证。
- `solidify.py:708` 的 `score: 1.0` 改为级联进度分（该字段语义在 Sprint 22.2 已定义，只是没开）。

**5.26.3 严格门控与 r_best 状态**

- 引入 `evolution_fitness_state.json`：`{baseline, r_best, history[]}`（对标 wikiskill `state.json`，但落在既有 `EVOLUTION_DIR`）。
- `enable_acceptance_gate` 转默认 **on**（先影子模式跑一个 Sprint 收集 `interception_rate`/`false_kill_risk`——`gep/acceptance/report.py` 已支持，这是 wikiskill 没有的谨慎手段，用它来降低转正风险）。
- 判决条件对齐：接受 ⇔ `R_val > r_best`（严格大于）；拒绝 → 回滚（既有机制）+ 失败事件记账（`enable_failure_events` 一并转 on）。
- 早停：`r_best == 1.0` 且连续 k 轮无改进 → 周期降频（复用 `enable_idle_scheduler`）。

**5.26.4 train/val 分割纪律**

- 基准任务强制 `split` 字段；**选择器与诊断只看 train 侧轨迹，门控只跑 val 侧**——防信号提取对评估集过拟合（wikiskill 的 split 纪律 + 本仓库 `experiment/trigger_shift` 过拟合评估器，两者合体）。

**5.26.5 评估隔离（最小版）**

- 验收门评估在 `git worktree` 干净副本中执行（本仓库已有 `gep/bridge.py` worktree 桥——直接复用，这是 wikiskill 用隔离 profile 达成的同一保证的 git 原生等价物）。

**验收标准**：
1. 默认配置（零 flag 覆盖）下跑 `evolver bench init && evolver --loop`，一次完整周期产生**非 1.0 的 score**；
2. 故意注入一个有害变异（如删除一个测试断言的基因提案），门控必须在 val 上否决并回滚，且失败事件入账；
3. 影子门控报告连续 7 天 `false_kill_risk < 0.1` 后，验收门才转执法模式。

---

### S27 — 知识层独立（P1，2 周）

> 目标：知识与技能获得独立生命周期；被拒记忆成为主路径。

| # | 工作项 | 落点 |
|---|---|---|
| 27.1 | 建 `wiki/` 层：`<EVOLUTION_DIR>/wiki/{index.md, log.md, skill-impact.md, patterns/}`，独立 git 仓（`git init` 于该目录），**不受 `EVOLVER_ROLLBACK_MODE` 影响** | 新模块 `gep/wiki.py`（对标 wikiskill `wiki.py` 的 46 行：骨架 + 审计提交，内容由既有 distill/reflection 管道写） |
| 27.2 | 收编投影：LESSONS_LEARNED.md 的摩擦点、memory_graph 的 preferred_by_signal、诊断簇（`enable_diagnosis_cluster`）定期投影为 `patterns/*.md` 人类可读页；原始 JSONL 保留为机器层 | `gep/wiki_projection.py` |
| 27.3 | **被拒记忆主路径化**：`enable_lineage_lessons` 转默认 on；被拒胶囊的指纹 + diff 摘要 + 拒绝原因全文写入 `wiki/skill-impact.md`（对标 `prompts.py:123-142`）；`prompt.py` 注入硬约束段：「以下方案已被验证失败，不得重复其指纹」 | `solidify.py:611-627` 已有指纹，接线即可 |
| 27.4 | 运行报告 `evolver report`：逐周期判决（接受/否决/无操作 + r_best 曲线 + 花费）生成 markdown，负面结果必须原样呈现 | 复用 `scripts/human_report.py` 扩展 |
| 27.5 | 回滚隔离测试：技能回滚后断言 `wiki/` 内容不变（对标 `test_harness.py:133-149`） | `tests/gep/test_wiki_no_rollback.py` |

**验收**：一次否决周期后，`wiki/skill-impact.md` 新增完整条目；下个周期的 GEP 提示词包含该条目；删除技能的回滚不触碰 wiki 仓。

---

### S28 — 轨迹诚实（P1，1–2 周）

| # | 工作项 | 落点 |
|---|---|---|
| 28.1 | **不可变证据层**：`raw/traces/<cycle>/` 只追加目录；`traces.save()` 已存在即抛错（语义照搬 `traces.py:27-41`）。现有 `gep/trajectory/` 重建器改为**消费**该层而非各自抓取 | 新模块 `gep/evidence.py` |
| 28.2 | **启动失败检测**：轨迹入库前检查工具调用计数；零调用 → 分类 `launch_failure` 而非 `zero_output`，供信号层区分「没干」与「干不了」 | `trajectory/builder.py` + `signals.py` 新增信号类 |
| 28.3 | **评估前沙箱重建**：bench 任务执行器每次 materialize 时删除规格外文件（`force=True` 语义，对标 `tasks.py:80-104`） | `bench/` 子系统内 |
| 28.4 | 事故回归测试文化：每修复一个评估缺陷，补一条以事故命名的回归测试（对标 `test_fresh_sandbox_prevents_stale_scores` 等） | 测试规范增补 |

**验收**：手工重放一个历史周期，证据层哈希逐字节一致；模拟死会话，信号层输出 `launch_failure`。

---

### S29 — 提案化变异（P2，2–3 周）

> 目标：把外部 agent 的自由度从「改代码」收窄为「交提案」，solidify 从「验证器」升级为「应用器+验证器」。

**5.29.1 GeneProposal schema**（对标 `prompts.py:114-117`，扩展为本仓库形态）：

```
{ "action": "patch" | "create" | "no_action",
  "gene_id": "...",
  "edits": [ {"op": "append|replace|insert_after", "target": "<锚点文本>", "content": "..."} ],
  "expected_signals": [...], "expected_fitness_delta": "..." }
```

**5.29.2 机械应用**：`solidify` 新增 `--apply-proposal <file>` 模式——锚点不中即拒（`ValueError`），应用前自动 `commit_base` 快照。既有 `hooks/ast_merge.py`（拒绝删顶层函数）与 `enable_constrained_genes` 作为提案应用的第二道约束层一并转 on。

**5.29.3 提示词改造**：`gep/prompt.py:74` 的 GEP 提示词输出要求从「请修改代码」改为「请输出 GeneProposal JSON」；桥模式（`sessions_spawn`）的回收协议相应改造。

**5.29.4 no_action 显式化**：选择器无可操作信号时产出 `no_mutation` 事件入账（对标 `harness.py:140-147` 的 no_action 记账），替代静默跳过——使「不进化」也成为可审计的决策。

**验收**：外部 agent 返回非法锚点提案 → 零文件变更 + 失败事件入账；返回有效提案 → 应用 + 级联验证 + 门控全流程无人工介入。

---

### S30 — 判定、迁移与瘦身（P2，滚动）

**判定与迁移**：

| # | 工作项 | 落点 |
|---|---|---|
| 30.1 | `evolver compare <wsA> <wsB>`：配对精确二项检验（纯 stdlib 实现，算法照搬 `compare.py:29-40`）挂主 CLI；`experiment/` 的 z 检验/Wald CI 作为参数化备选 | `cli.py` + `experiment/compare.py` |
| 30.2 | `evolver transfer <src> <dst>`：技能跨工作区/跨宿主迁移，落 dst 自己的 git 历史以便回滚（对标 `transfer.py:55-63`）；`skill2gep.py` 增反向 `gep2skill`（SKILL.md 生态互通） | 新命令 |
| 30.3 | 发布决策点：是否上 PyPI（OIDC 无 token 发布可直接抄 wikiskill `release.yml`）；文档站 mkdocs 化 | 决策条目 |

**瘦身专项（与上述并行）**：

| # | 工作项 | 目标 |
|---|---|---|
| 30.4 | 环境变量治理：~196 → 分组文档化；僵尸变量（清点于 25.5）废弃流程 | ≤80 个在用 |
| 30.5 | flag 层收编：S26–S29 转正后，被吸收的 flag 进入废弃期（两版本后删除）；目标 26 → ≤12 | 实验层与主路径界限清晰 |
| 30.6 | 依赖审计落地（25.4 结论执行）：可选依赖移入 extras；评估 GitPython→subprocess | ≤8 个核心依赖 |
| 30.7 | 重复实现合并评估：JSON+JSONL 叠加 vs SQLite（`ops/sqlite_store.py`）二选一；多蒸馏器变体收敛入口 | 出合并决策，不强制当季执行 |
| 30.8 | 运行时状态出仓评估：`memory/`、`.evolver/` 移出版本控制（保留种子与参照快照） | 代码/数据边界清晰 |

**验收**：`evolver compare` 对已知结果集给出与手算一致的 p 值（对标 `test_compare.py` 的 `(10,0) → 2/2^10` 断言）；瘦身各项有决策记录。

---

## 6. 里程碑总览

| 阶段 | 主题 | 优先级 | 预估 | 前置 |
|---|---|---|---|---|
| S25 | 冻结与基线固定 | — | 1 周 | 无 |
| S26 | 适应度革命（bench + cascade 转默认 + 严格门控） | **P0** | 2–3 周 | S25 |
| S27 | 知识层独立 + 被拒记忆主路径 | P1 | 2 周 | S26（门控产生真实拒绝才有内容可记） |
| S28 | 轨迹诚实三件套 | P1 | 1–2 周 | 可与 S27 并行 |
| S29 | 提案化变异 | P2 | 2–3 周 | S26 |
| S30 | 判定/迁移/瘦身 | P2 | 滚动 | S26 起随时可动 |

**最终愿景**：evolver.py 从「提示词生成器 + 事后验证器」演进为「自带可测适应度的闭环进化引擎」——能够回答 wikiskill 在 README 里提出的那个问题：*「技能到底有没有用？」*，并且用配对统计给出 p 值。

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| cascade 转默认后大量周期被否决，「进化停滞」的观感 | 影子门控先行一个 Sprint（`interception_rate` 可见）；`evolver report` 把否决呈现为**系统在正常工作**而非失败（wikiskill 的负面结果公开文化是最好的范本） |
| 基准任务过拟合于本仓库自身 | 三层任务来源（内置/仓库/用户包）+ train/val 分割 + `trigger_shift` 评估器 |
| 提案化破坏与 Node 原版的桥模式兼容 | 提案模式走新 flag（先 off 后转正），桥模式旧路径保留一个废弃期 |
| 瘦身触动既有测试契约 | 瘦身一律「先决策后执行」，每项独立 Sprint，沿用「字节级兼容」纪律 |
| 上游 Node v2 线再次拉开 | 已决策转维护模式；仅安全类（如 GHSA 后续）保留插队权（沿用 D9 决策） |

---

## 附录 A — wikiskill 速查（供实施时对照）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `bench.py` | 423 | 22 任务确定性生成器（六任务族 + 陷阱断言） |
| `cli.py` | 228 | 11 子命令 |
| `harness.py` | 152 | Algorithm 1 编排（train→maintain→propose→gate） |
| `gating.py` | 145 | 状态/提案应用/回滚/单任务运行/门控 |
| `compare.py` | 143 | 配对精确二项检验 |
| `prompts.py` | 119 | 三角色提示词（论文 Appendix E 改编）+ 门控记账格式 |
| `tasks.py` / `transfer.py` / `traces.py` / `scoring.py` / `wiki.py` | 85/69/57/52/46 | 任务校验/迁移/不可变轨迹/评分器/wiki 骨架 |
| `backends/` | 534 | AgentBackend 协议（7 方法）+ hermes/claude 后端 + 转录归一化 |

## 附录 B — 本仓库关键证据索引

| 论断 | 证据 |
|---|---|
| 成功 score 硬编码 1.0 | `src/evolver/gep/solidify.py:708` |
| 26 个 flag、13 个实验层默认 off | `src/evolver/gep/feature_flags.py:35-102` |
| 谱系教训/新颖性门/验收门/级联默认 off | 同上 `:52,:62,:71,:74` |
| 被拒胶囊只作提示词预览字段 | `src/evolver/gep/prompt.py:90,180` |
| experiment 未挂主 CLI | 原《演进方案.md》§3.2 |
| 验收门影子模式已就绪 | `src/evolver/gep/acceptance/report.py:21-45` |
| worktree 桥可复用于评估隔离 | `src/evolver/gep/bridge.py` |
| 失败事件机制已造好但未开 | `feature_flags.py:91`（`enable_failure_events`） |

---

*本方案之元教训：wikiskill 用 2,093 行代码 + 0 依赖实现的闭环，正是本仓库用 51,645 行 + 26 个 flag 许诺的闭环。演进的方向不是再加机制，而是把已有机制从 flag 后面请到主路径上来，并用一个可测的基准证明它们工作。*

---

## 8. 实施收口（2026-09-01，Sprint 26–30 交付回执）

> 本节为实施完成后的状态快照。全部改动零拆除、零 parity 破坏，版本 1.96.0，3257 用例全绿，ruff/mypy 全绿。

### 已落地（按方案条目）

| 方案条目 | 交付物 | 状态 |
|---|---|---|
| S25.1 parity 转维护 | 用户拍板 B；CHANGELOG 1.96.0 | ✅ |
| S25.5 环境变量清点 | `scripts/env_inventory.py` + `docs/env-registry.md`（实测 **234** 个） | ✅ |
| S25.4 依赖审计 | `docs/dependency-audit.md`：**14 → 10**，移除 click / pydantic-settings / GitPython / boto3（全部零引用） | ✅ |
| S25.3 基线快照 | `scripts/baseline_snapshot.py`（git HEAD / flags / fitness 账本 / 事件统计；93 条历史事件均无测量分——转正前后对照基线） | ✅ |
| S26.2 适应度转正 | `enable_fitness_cascade` 默认 on + PATH 过滤 + 诚实 score（测量分 vs `unvalidated: true`） | ✅ |
| S26.2 失败记账 | `enable_failure_events` 默认 on | ✅ |
| S26.3 影子门控 | `enable_acceptance_gate` 默认 on + `EVOLVER_ACCEPTANCE_SHADOW=true` | ✅ |
| S26.3 r_best 严格门控 | `gep/fitness_state.py`（`R > R_best` 严格比较，影子期；执法 `EVOLVER_FITNESS_GATE_ENFORCE=1`） | ✅ |
| S26.1 bench 全套 | `src/evolver/bench/`：health 任务 / wikiskill 格式任务包 / 四评分器 / 幻影评分防御 / `bench list·run·prompt·grade·compare` | ✅ |
| S26.4 train/val | `run --pack --split`：gate 只看 val；pending 排除；空集不记账 | ✅ |
| S27 知识层 | `gep/wiki.py`：独立 git 仓、永不回滚；四处判决接线；回滚隔离有测试锁定 | ✅ |
| S27 被拒记忆主路径 | GEP 提示词 `## Wiki Impact` 段（默认注入，不依赖 flag） | ✅ |
| S28.1 证据层 | `gep/evidence.py`：架构级不可变（二次写抛错），重放逐字节一致 | ✅ |
| S28.1+ 沙箱重建 | bench `materialize(force=True)`（幻影评分防御），随 S26.1 提前交付 | ✅ |
| S29 提案化变异 | `gep/proposal.py`：锚点精确唯一校验 / 两遍法零部分应用 / 路径逃逸拒绝 / `apply-proposal` CLI；顺带修复 `__main__.py` 退出码 | ✅ |
| S30 统计判定 | `bench/compare.py`：配对精确二项检验（`(10,0)→2/2¹⁰` 契约锁定）；小样本诚实报无显著差异 | ✅ |
| S30.8 第一片 | `disk_flags.json` 出仓 + gitignore（运行时状态热更新文件不入仓） | ✅ |

### 移交余项（维护级，按需触发）

| 余项 | 说明 | 触发条件 |
|---|---|---|
| ~~S27.2 patterns 投影~~ | **已交付（1.97.0）**：`gep/wiki_projection.py`，确定性幂等投影，`evolver report` 触发 | — |
| ~~S27.4 `evolver report`~~ | **已交付（1.97.0）**：`gep/report.py` + CLI `report [--output] [--limit] [--no-project]`，负面结果原样呈现 | — |
| ~~S28.2 启动失败信号化~~ | **已交付（1.97.0）**：`launch_failure_detected` 信号 + `count_launch_failures`；trajectory 导出经 pending-signals 管道自动入下周期信号 | — |
| S26.5 worktree 评估隔离 | 验收门在干净 worktree 跑；影子期非阻塞 | 验收门转执法（soak 期满）前 |
| S30.4–30.7 瘦身余项 | env 合并 / flag 废弃期 / fastapi·uvicorn·mcp·keyring 移 extras / 存储二选一 | 依赖审计文档已给路线 |
| S30.2 transfer | 跨工作区迁移已有 `scripts/a2a_export.py`/`a2a_ingest.py` 覆盖；`gep2skill` 反向待生态需求 | 出现真实多工作区用户 |
| 发布决策（S30.3） | PyPI OIDC + mkdocs | 引擎带新门控跑出首批 soak 数据后 |

### 下一步建议

1. **让引擎带新门控跑 1–2 周 soak**（acceptance gate 影子期 + fitness 影子期收集 `interception_rate`/`false_kill_risk`）；
2. `evolver bench run` 每日 cron 一次，r_best 账本开始积累真实测量史；
3. soak 数据良好后 `EVOLVER_ACCEPTANCE_SHADOW=0` + `EVOLVER_FITNESS_GATE_ENFORCE=1` 转执法；
4. 然后再评估剩余维护项。

### 审阅勘误（2026-09-01 双轴审查后修正）

1. **boto3 误删（P0，已修复）**：S25.4 审计初版误报"零引用"（扫描深度不足漏检 `messages_route.py` 三处惰性导入）→ 已移入 `[project.optional-dependencies] bedrock`，文档已勘误。
2. **r_best 量纲混杂（已修复）**：cascade 分与 bench 分曾共用一个 r_best，一次 cascade 1.0 会永久锁死 bench 改进空间 → 账本改为**按度量域分离**（`cascade` / `bench:health` / `bench:pack:<split>`），旧格式自动迁移，跨域不互锁有测试锁定。
3. **wiki 防追踪加固（已修复）**：`ensure()` 现在幂等地把 wiki 路径写入父仓 `.gitignore`——堵住「父仓自动提交 + reset --hard 回滚知识」的洞，新增场景测试锁定。
4. **S26.3 验收标准 2 补齐（已完成可测化身）**：新增有害变异端到端测试（proposal 注入有害编辑 → 级联否决 → 工作树回滚 → 失败事件 + wiki 证据链）。bench-val 侧的有害注入需 agent 执行器，列入移交。
5. **交付缩水声明**：S26.1 内置基准实际为 3 个 health 任务（非"对标 22 任务"）；`bench import` 由 `run --pack` 承担；评分器自洽测试仅锁 `exact`。S27.2 patterns 投影与 S27.4 `evolver report` 未实施。S27.3 谱系字段在 `enable_lineage_lessons` 默认 off 时不生效（此为 flag 纪律，非缺陷）。
   **→ 后续补齐（同日）**：`bench/builtin_pack.py` + `evolver bench init` 提供确定性 12 任务内置包（五任务族含生成时陷阱断言，两次生成逐字节一致），四评分器自洽测试全量锁定（exact/contains/json_field/code_stdout）；`load_pack` 统一接受 wrapped 与裸列表格式。
6. **已知权衡（记录不改）**：evidence 不可变性由 `suppress` 包裹（wiki 故障不得阻断 solidify 的取舍）；`bench run` 的 0.999 → exit 1 为故意严格；conftest 哑级联意味着真 ruff/mypy/pytest 默认路径只在 CI 全量跑中覆盖。
7. **bench pytest-fast 超时误判（2026-09-02 独立审计发现，已修复）**：`HEALTH_TASK_TIMEOUT_S=300s` 低于本机 not-slow 全量真实时长（~310s）→ `TimeoutExpired` → 永久误判 fail（R 恒 0.5）。这正是验收标准 1 要防的**假测量**——score 非 1.0 但原因是测量面而非仓库。修复：bench 复用 cascade 之 `FITNESS_PYTEST_TIMEOUT_MS`（600s，env 可覆盖），单一真相源；回归测试锁定两处超时相等。修复后 `bench run` 实测 R=1.0。
