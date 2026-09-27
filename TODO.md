# evolver.py 工作清单

> 章程：[`演进方案.md`](演进方案.md)（配对会话，版本钉 **1.112.0**）。
> 按轮记账：[`CHANGELOG.md`](CHANGELOG.md)。
> [`RSI演进对照.md`](RSI演进对照.md) 与 [`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md) 是史料。不要从史料里的「下一步」开工。
> 2026-09-24 外部适应度的两步（重复失败走 `swarm_propose`、冻结任务包）已落地，继续有效。下表是新的发布规则。

## 现在做

round-87 闭了第 3、4、5 项：大包（val > 6）发布走 `bench/compare.py` 配对检验（α = 0.05，discordant ≥ 8，raw-score floors 让位于配对检验、自报 declaration 仍绑定）；enrich 把已发布库快照作只读设计上下文注入 prompt、run record 记查阅 id（active 对比期间仍指 Parent）；无会话的 `--loop` tick 返回 `stop_and_report` 不写基因，守护循环即停。机器部分全部接完，只剩第 6 项收口——它要真实运行数据，不是代码。

round-88 把仪器装上了（真机，仓外 soak 根）：锚纪元 13 全绿、章程包冻结（12 题，digest `721a33d8de3a0b6e`）、Parent 基线 1.0（5 题 val × 2 遍，per_task 地板与 epoch 绑定齐全）。**bar 在天花板**：此包下「严格优于」打不穿，第 6 项只剩两条路，由人点名——换更难的包（`bench freeze --force` 作废基线重测），或起首次配对会话走八会话分支。全量回归 3967 通过，首次有全量数字。

| # | 项 | 完成时 |
|---|---|---|
| 6 | 收口 | 协议生效后：若有一次章程第 4 节定义的 Accept，提请人切 minor。若八次会话结束仍没有这样的 Accept，把说法收窄为「受治理的仓库自维护」，并关掉从未赢过的臂 |

## 已完成（round-87）

- 大包配对检验：`gate_verdict` 在 val 题数 > `REPLICATE_VAL_MAX` 时走 `_paired_verdict`——每轮须候选赢方向（p ≤ 0.05）且 discordant ≥ 8 才发布；大包不跑 raw-score floors（配对检验即不退化断言），`declaration` 先于配对检验断言；`baseline_without_per_task` / `task_set_mismatch` / `parent_better` / `not_enough_discordant` / `no_significant_difference` 分别拒绝且不动基线。
- 环内查阅：enrich `_consult_library` 渲染 `library_block`（只读、4000 字符截断带标记），dispatch 挂进 prompt、solidify state 记 `library_snapshot`。
- 游标停止语义：无会话 tick `next_action=stop_and_report` 且不进管线；`run_loop` 收到即 break；到期提醒随报告捎带。

## 已完成（round-86）

- solidify 折账先 `begin_round`：候选 id 取 pending 周期的 mutation id，假说文本在焚毁前先读；`cycle_ref` 幂等防重烧；`rounds.jsonl` 带 `cycle_ref`。
- 假说归属：`require_for_gate` 增 `also_accept`（周期 id ∪ 当前会话轮 id）；CLI `session hypothesize` 优先盖 pending 周期 id。
- 不许退化项断言（`bench/regression_guard.py`，基线 v1 带 `per_task`，候选可追加只许收紧）、门入参有限性（NaN/inf 拒）、验收协议冻结（基线绑 `anchor_epoch`）。
- `gep/library.py`（发布不覆盖、按 id 读不碰 active）、`gep/cursor.py`（只在 Accept 推进）落树并接线会话机与循环门。

## 守住

这些不是待办，是本阶段的边界。

- 版本保持 1.112.0，直到人宣布阶段结束。
- `EVOLVER_ACCEPTANCE_SHADOW` 保持打开。真阳性仍由人登记到 `$EVOLVER_HOME/anchor/gate-verifications.jsonl`。
- 产品仓不提交 `memory/` 运行态，也不提交已发布的库快照。快照在仓外，按内容哈希保留。
- 宿主上报的 `primary_score` 来自级联或门的结果。
- 回归地板是级联和锚。宿主不能自加预算，也不能自报「无回归」。

## 不做

- 移植本体五类记录、本体可视化、LLM Judge、插件市场。
- RSI P2-6 / P2-8 / P2-9。
- validator 安全模型重写、ATP 商业闭环、PyPI、把拆 `cli.py` 当作独立项目。
- 打开 `enable_event_history`、bandit、niche、novelty gate、operator bandit、K=2 种群。
- 把 soak `ready` 当作本阶段出口。
- 再开一轮只修测量仪器或测试针的 dogfood，并把它算成阶段进度。
- 环内修改冻结包、val 期望或评分规则。
