# evolver.py 工作清单

> 章程：[`演进方案.md`](演进方案.md)（外部适应度，版本钉 **1.112.0**）。
> 按轮记账：[`CHANGELOG.md`](CHANGELOG.md)（dogfood 至 round-78）。
> [`RSI演进对照.md`](RSI演进对照.md) 与 [`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md) 是史料。不要从史料里的「下一步」开工。

## 现在做

| # | 项 | 完成时 |
|---|---|---|
| 1 | 重复失败走提案 ✅ round-79 落地 | Evidence Pack 判定该信号族已固化未消、或已接受路径仍失败时，instrument 要求 `swarm_propose`。自由编辑只留给新颖信号和结构性改动。固化事件记录级联分 |
| 2 | 冻结任务包接入周期 ✅ round-79 落地（已 `bench freeze`，digest `42bc0fcb5771bccb`） | `evolver.bench` 的一个包成为附加接受条件：分数下降则拒绝；持平或上升，且级联与锚通过，才接受。评分规则放在仓外或锚侧，环内不得改 |
| 3 | 收口 | 约十个这样的周期之后：若有一次被接受的 diff 不落在 `acceptance/`、`ops/meta_report.py`、`ops/charter_check.py`、`ops/capability_trace.py` 和测试针上，且包分不降、锚全绿，提请人切一次 minor。若被接受的仍全是仪器向变更，把说法收窄为「受治理的仓库自维护」，并关掉从未赢过的臂（种群若无胜者；仍默认关闭的 bandit、niche、ATP bridge） |

## 守住

这些不是待办，是本阶段的边界。

- 版本保持 1.112.0，直到人宣布阶段结束。
- `EVOLVER_ACCEPTANCE_SHADOW` 保持打开。真阳性仍由人登记到 `$EVOLVER_HOME/anchor/gate-verifications.jsonl`。登记与否不阻塞上表。
- 产品仓不提交 `memory/` 运行态。进化目录用仓外 soak 根。
- 宿主上报的 `primary_score` 来自级联或门的结果。

## 不做

- RSI P2-6 自博弈出题、P2-8 继承工件视图、P2-9 多节点共享进化素材。
- validator 安全模型重写、ATP 商业闭环、PyPI。
- 把拆 `cli.py` 当作独立项目。
- 打开 `enable_event_history`、bandit、niche、novelty gate、operator bandit。
- 把 soak `ready` 当作本阶段出口。
- 再开一轮只修测量仪器或测试针的 dogfood，并把它算成阶段进度。
