# evolver.py 工作清单

> 章程：[`演进方案.md`](演进方案.md)（库即尺子，版本 **1.113.0**）。
> 按轮记账：[`CHANGELOG.md`](CHANGELOG.md)。
> [`RSI演进对照.md`](RSI演进对照.md) 与 [`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md) 是史料。不要从史料里的「下一步」开工。
> 2026-09-24 外部适应度的两步（重复失败走 `swarm_propose`、冻结任务包）已落地，继续有效。下表是新的发布规则。

## 现在做

配对会话阶段已收束（round-90）：八次会话、16 Reject、0 Accept，门证明的是治理机器能拒绝发布。版本切 **1.113.0**。本阶段叫**库即尺子**：被进化的对象本身成为评分对象——被评分的是库快照，不是宿主的细心程度，也不是再写一份更难的微任务。

账上的两个洞：八场 `parent_snapshot` 全 null（没有 Parent 库首写，「active 不动的 Parent/Candidate val 评分」从未发生，跑过的只是仓库 diff 对宿主微任务）；16 条 `hypothesis` 全空串（周期先焚毁、折账后读——round-91 已修，卫生账；历史空串**不回填**）。

| # | 项 | 完成时 |
|---|---|---|
| 1 | ~~补账本~~ | 已完成（round-91 卫生账，不算阶段进度）：`solidify()` 在 `_solidify_cycle()` 之前取假说正文交给 `begin_round` |
| 2 | Parent 库首写，入口独立 | 引擎先落新函数（`establish_*` 族，`evolver bench baseline` 同一纪律：不带变异、solidify 调用不到），带自己的命令行入口；**不给 `publish()` 加入口**（首写和 Accept 不得合用一条路，publish 保持 Accept-only）。函数就位后由人写第一份 Parent 库 |
| 3 | 条款来自 train，val 题面不含条款 | 决定性条款必须能从 train 的前后观察里唯一收回，val 题面不出现。Parent 求解只看 Parent 快照 + val 题面；候选求解只看候选快照 + 同一批 val 题面；写候选的宿主看 train，不看 val、不看 grader。空库 Parent 拿不到 train 蒸馏的约定；若 Parent 仍满分 → 宿主不读库也能猜中，测量结束，不改题面再测。「家规只在写库人脑子里」的旧设计已废（round-92：空库钉 Parent 于 0、首份候选靠抄写白得 Accept，是出题人给候选写及格线） |
| 4 | 按快照 id 读 | 求解入口按 id 注入：Parent 求解放 Parent 快照 id，候选求解放候选快照 id，都走 `load_version()`，都不动 active。不复用 enrich `_consult_library()`（读 active；候选草稿条款不在那里）。现在 `bench prompt` 只有题面和沙箱，库不在场 |

第 3 步按上表修正之前**不写 Parent 库、不出新题**。完成判据同步收窄：「库里有句子、答卷里有句子」的 Accept 只证明求解路径读了快照，不算；本阶段的 Accept 是候选快照条款只来自 train 观察、val 求解只靠这份快照、两遍严格高于只持有 Parent 快照的 Parent。

不开第三份「把宿主难住」的包。Evolver.php（2026-04 / v1.69）与 EvoScientists 分叉不追这次协议。

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

- 版本 1.113.0（配对会话阶段收束，2026-09-27）。下一阶段结束由人再切。
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
