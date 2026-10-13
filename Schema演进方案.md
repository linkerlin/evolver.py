# Schema 演进方案

> 2026-10-13 起草。同日三次修订：先按两条裁决改为与现行章程并行、只取思想；再按审阅改为渐进增强；最后把落地收成一句提示词。这句已进代码（见 CHANGELOG「满分基线上的持平拒绝」）。其余条目未排期。
> 对照：arXiv:2609.39140《Schema: Discovering Unknown Environments via Agentic Program Induction》（Zeng 等，2026-09）与 [schema-harness.github.io](https://schema-harness.github.io/)。
> 现行章程是 [`演进方案.md`](演进方案.md)（经验即证据）。本文件是它的并行补充：不替换、不归档、不另开出口、不另建账本。开工与否由人定；开工的条目写进 [`TODO.md`](TODO.md)。
> 版本 **1.113.0** 不动。台账只记 [`CHANGELOG.md`](CHANGELOG.md)。
> 论文名 Schema 与本仓假说维「图式」（`gep/hypothesis.py` 的 `schema`）撞名。本文件里 Schema 只指那篇论文。

## 0. 已裁

1. **并行，且共用对象。** 只读、只渲染现行章程已有的东西：episode record、线索层、假说、dispatch 提示词。不新增存储、MCP 工具、环境变量；不改任何门的裁决；不改 episode 格式；不动消融的两臂。
2. **取思想，不取 harness。** `step()`、回测器、搜索器、`commit_actions`、三套游戏基准都不迁。
3. **一次一步。** 每步一个可回退的小提交；先看真实提示词，再走下一步；后几步等数据出现再做（§4 的触发条件）。

## 1. 已经有的，不重建

Schema 的几根柱子，本仓已经以自己的形状立着。审阅时逐条对过，下列各项不再动：

| Schema | evolver 现成件 |
|---|---|
| 只追加、智能体改不了的 Timeline | `gep/episode_record.py`：内容寻址、写后不可变、调用图钉 |
| 每次修订对全历史回放（去掉 −10.6pp） | 验证级联（全量测试）、`bench/regression_guard.py` 的逐题地板、仓外锚 |
| 行动前先登记预测 | 假说门：solidify 测量之前必须有假说，`mechanism_check` 要 train 上的 before/after |
| 现实高于模型 | 记录分层：证据 = 引擎自记 + relay，宿主上报 = 线索 |
| 预测错了就停（去掉 −20.5pp） | 每轮独立过门；HOTL 连续降级自动暂停；证据包的 `PROPOSAL REQUIRED` |

已补上的一件：下一轮看到的结局只有 `failed`。包门拒绝且分数持平、基线已满分时，dispatch 在摘要后加一句，说明这一轮测不出假说对错。假说在结算后焚毁、下一轮看不到自己上一轮说了什么，这件知道，未排期。

## 2. 取来的思想

1. **否定只覆盖测到的部分**（论文 LF52、DC22）。门在测量之前拒绝的一轮、改动没站住的一轮、Parent 已满分而测不出提升的一轮，都不说明假说对错。soak 的 24 次拒绝里有 19 次属于最后一种（`bench_pack_rejected`，`flat`，基线 1.0）。这一条已落地，见 §4。
2. **预测与观测并排，错了先改说法**（逐步核对的消融）。未排期。
3. **补规则不灵就换表示**（WA30、KA59）。只在「已测、未见提升」重复出现时才有意义。未排期。
4. **发现一次，后面复用**（MazeBench）。没有一次被接受的结算，就量不出「之后」。未排期。
5. **否定一格，不牵连整族**（LF52）。现有基因几乎都不标 `mechanism_family` / `target_hook`，按格分组目前分不出东西。未排期。

## 3. 渐进规则

- 先改锚验证面之外的文件（`swarm.py`、`cli.py`、`evolve/pipeline/dispatch.py`、`gep/episode_clue.py`、`gep/episode_record.py`）。必须碰 `config.ANCHOR_TRIGGER_SURFACES` 里的文件（`prompt.py`、`evidence_pack.py`、`meta_report.py`、`hypothesis.py`、`solidify.py`）时，本步跑 `uv run evolver anchor run`，并在 CHANGELOG 写明。
- 不改 `render_episode_block`。消融的 `--from-episodes` 臂调用它；它的输出不变，现行出口的对照就不受影响。dispatch 需要多显示的东西，在 dispatch 里拼到这段文本之后。
- 只转向，不结算。新增的读数与线索只进下一轮提示词，不进 solidify、验收门、冻结包门、选择器、消融裁决。
- 每步：先写失败测试 → 最小改动 → `uv run ruff check src tests`、`uv run mypy src`、`uv run pytest` → CHANGELOG 一节（版本不动，不计「经验即证据」出口进度）→ 用一次真实 dispatch 输出（soak 或 Tier B）看提示词。看过再做下一步。
- 回退即撤销该提交。已落地的那一句只存在于当轮提示词，不落盘。

## 4. 已落地，以及未排期

已落地，且只此一件：`ceiling_tie_note`。上一轮正文同时满足 `outcome.error=bench_pack_rejected`、`pack_reason=flat`、`gates.bench_pack.baseline=1` 时，dispatch 在 episode 摘要后加一句「基线已满分，分数持平，这一轮测不出假说对错。」三个字段缺一、基线低于满分、或结局是变差，都不加字。`render_episode_block` 未改。

未排期（人点名才做）：

1. 八类结算读数表。除「持平且基线满分」外，其余错误码在现有数据里几乎没有样本。
2. 上一轮假说留作线索。要动两个结算入口，还要处理线索块 1200 字符从尾部截断。
3. 同一说法重复未被支持时提示换表示。触发：至少两条测到了假说、却未见提升的结算。
4. 两段开销进遥测。触发：episode 索引出现第一条非 `failed`。`meta_report.py` 在锚面上。
5. 证据包按格显示拒绝。触发：同一信号族里出现至少两个不同的 `target_hook`。`evidence_pack.py` 在锚面上。

## 5. 不取

| 条目 | 理由 |
|---|---|
| 引擎执行宿主写的世界模型 | 本仓的动作是一次 diff，模拟不了；引擎会成为第二个执行器 |
| 理论版本库、train 时间线、预测日志 | 现行章程不再造平行账；需要的都在 episode 与线索层 |
| 新的提交通道、新的暂停 | 落地只走 solidify，停机只走 HOTL |
| 模型内搜索、四臂消融、游戏基准适配器 | 没有可搜索的状态图；出口留在现行章程的有 / 无记录对照 |
| 冻结包改成隐规则游戏、val 上跑程序 | 冻结包是门；val 求解者须与 Parent 相同 |
| 改 Gene schema、库快照携带程序 | `extra="forbid"` 与快照定义不动 |
| 宿主点名 episode id、按「覆盖」判断换表示（上一稿） | 宿主没有点名的通道；「覆盖既往轮次」对一次 diff 没有对应物。全历史回放已由级联、地板与锚承担 |
| `expected_effect` 与结局并排（上一稿） | `expected_effect` 是引擎模板（`gep/mutation.py`：`Address signals: …`），不是宿主说法；宿主的说法是假说 |

## 6. 文档职责

| 文件 | 职责 |
|---|---|
| [`演进方案.md`](演进方案.md) | 现行章程：比什么、何时停 |
| 本文件 | 并行补充：从 Schema 取哪几条、按什么节奏落 |
| [`TODO.md`](TODO.md) | 唯一的开工清单 |
| [`CHANGELOG.md`](CHANGELOG.md) | 按 round 记账 |
| [`DEBUG.md`](DEBUG.md) | 排障账 |
