# evolver.py 工作清单

> 当前阶段章程：[`演进方案.md`](演进方案.md)（蜂群闭环稳定化，v1.112）。
> 长期差距 / Sprint 26–30 回执：[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)。
> RSI 分级路线：[`RSI演进对照.md`](RSI演进对照.md)（§五 实况审计、§六 effective-L5 实验）。
> Node 对标基线仍是 v1.94.0；Python 线版本见 `pyproject.toml`。

## 当前状态（2026-09-19，round-37 交付后系统性审阅）

- 包版本：**1.112.0**（soak 封版中；「一阶段一 minor」，阶段切换留人类仪式）
- Dogfood：**37 轮**（round-30~34 曾五轮环旁路，round-35 对账揭出并回正；
  round-35~37 三轮连续环内干净运行）
- 测试：全套件 not-slow 级联全绿（T0 分母 **3653**，基线 0.999726 双重复一致）；
  ruff / mypy strict（327 文件）0 错误
- 验收门：`gated_cumulative=31`，滚动窗 20，`verdict=false_kill_high`
  （窗内 2 历史伪杀待滑出：预计 cumulative ≈40/42），
  `verified_true_positives=0`（**属实非欠账**：账本中尚无真实 T0 回归被门
  shadow 拒绝过，无可登记项），shadow_mode=on
- 锚定评测：**Epoch 10 × 15 探针**，9 次生产运行全绿（round-37 变异自身
  被实弹审判 15/15）
- 环完整性：`charter-check` loop_integrity = **ok**（round-37 新仪器；
  仓内视图 stale 112965s 与 soak 视图 ok 双视图各自如实）
- 运行态：外置 `~/.evomap/evolver.py-soak`（CLI/MCP/runner 自动路由）；
  仓内 git 运行态卫生 met=True；env 脚印 78/80

## 核对结论（本轮审阅发现，2026-09-19）

计划文档内部自洽（演进方案 §11.5–11.9 回填至 round-34；RSI §6.6 至
round-36；TODO P0/P1 全清）。以下为实况漂移与悬置项：

1. **CHANGELOG 按 round 记账中断**：round-30~34 有条目，**round-35~37 缺**
   （round-35 的三缺陷修复、round-36 复跑 #2、round-37 环完整性回执均未入账）。
2. **g1 谱系污染未清余波**：round-35 事件 `evt_…ea7446c7`（gene_id=g1
   劫持）仍在 soak 账本，**已两次传染下游**——round-36/37 tick 的 Recall
   Hints 出现 `g1 (gene)` 假成功经验，喂给选择器的是假记忆。
3. **守护进程古老代码仍在循环**：pid 35664（`evolver --loop`，2026-09-07
   启动=round-7 时代代码）已连续运行 12 天，未吸收此后 30 轮全部互锁。
4. **MCP server 孤儿进程 ×3**（10:51 / 14:19 / 14:19），其一早于 round-37
   代码；stdio 管道归属须 `ps` 核对。
5. **两个悬置人为决策**（引擎只能提示，无法代办）：
   - soak 转正三条件中 `verified_true_positives ≥1` 需**未来首个真实 T0
     回归被门拒绝时人工登记** `~/.evomap/anchor/gate-verifications.jsonl`；
   - v1.112 稳定化阶段的**收尾仪式**（§11.3 判词「阶段从未宣布结束」至今
     成立）：soak 判定落定后由人宣布阶段切换与下一 minor。

## P0 — 度量闭环与账本卫生（本轮起，均为小-中成本单轮变异）

| # | 项 | 内容与验收 | 依赖/风险 |
|---|---|---|---|
| 1 | **library 忠实使用率 + 每次验证成本口径** | `meta_report.py`：(a) 忠实使用率——落地基因在后续事件 `evidence_pack`/`recall` 中被检索且其 strategy 语义被执行器遵循的比例（P1-4 已留同源 `ctx["evidence_pack"]` 数据，检索到≠被遵循，需定义遵循信号：执行 diff 与基因 strategy 步的对应或事件 self-report）；(b) 成本口径——`validation_ms_per_validated_gain` 已有，补「每次固化的墙钟-费用换算表」（cascade+门+锚三段计时已在事件里，纯聚合）。验收：两指标入 `meta-report` 面板 + 单测 + 米尺面已入锚（探针不动即不升 epoch） | 无阻塞；**是 P2-3（P1-3 种群）的硬前置**（TODO P2 表注明的资源账口径即此） |
| 2 | **g1 事件 recall 隔离** | 谱系卫生：recall/evidence_pack 读事件时跳过已知失真事件（`gene_id` 不在当前基因库且为已知夹具名单，或事件带 `lineage_corrupt` 标注）。**不改账本本身**（append-only），只修消费端。验收：tick Recall Hints 不再出现 g1；evidence pack 记分板同口径；负向单测 | 需同步审视 selector 事件消费路径；避免造「事件白名单」机制过重——最小实现即可 |
| 3 | **CHANGELOG 补账 round-35~37** | 按 round-30~34 同格式补三条（#44 三缺陷 / 复跑 #2 / 环完整性回执），`check_changelog.py` 过。纯机械 | 无 |

## P1 — soak 转正路径（被动积累 + 挂钟，无需专项变异）

| # | 项 | 内容与验收 |
|---|---|---|
| 1 | **环内继续攒干净样本** | 每轮 dogfood 自然累积 gated 事件；cumulative 31 → **≈42**（两伪杀滑出滚动窗）后 verdict 自动重算。纪律不变：`EVAL_WORKTREE=1`、真实 friction 驱动、feedback 反映级联真分 |
| 2 | **人工登记首个 verified true positive**（人类动作） | 当首个**真实 T0 回归**被门 shadow 拒绝（cascade 绿、门拒绝、人复核确认回归为真）：`evolver anchor` 旁 `gate-verifications.jsonl` 登记 `event_id -> verdict`。此后 `verified_true_positives ≥1` 条件满足 |
| 3 | **effective-L5 复跑 #3** | 挂钟 ~round-46（§6.4 协议：每 ~10 轮）；届时跨纪元证据有望 3/3——若达，§2.2 L5 表述升级提案（文档变更走人审） |
| 4 | **verdict 落定后的转正决策**（人类动作） | 三条件齐后：人决定 `EVOLVER_ACCEPTANCE_SHADOW=0` 与否；同时宣布 v1.112 阶段收尾（§11.3 的「阶段切换仪式」）与下一 minor |

## P2 — RSI P1-3 候选种群（L2 跃迁最后一项，P0-1 完成后启动）

| # | 项 | 内容与验收 | 前置 |
|---|---|---|---|
| 1 | **K=2 worktree 并行候选** | 同一 run 产出 2 个候选（不同基因/策略），各自在隔离 worktree 过同一验证门，择优固化；谱系记 `sibling_of`。验收：并行跑通 + 择优入账 + 成本换算表显示每增益净成本未劣化（P0-1 的口径）+ 锚 epoch 11 冻结择优语义 | **P0-1 成本口径**（否则翻倍成本不可见）；预算守卫设计（每轮 wall-clock 上限）；S26.5 桥已默认开 |

## Ops — 环境卫生（用户决定/顺手）

| # | 项 | 说明 |
|---|---|---|
| 1 | 守护进程处置 | pid 35664（round-7 代码）建议 `evolver stop` 后按需 `evolver start`（新代码含 soak 自动路由）。**用户启动的进程，留用户决定** |
| 2 | MCP 孤儿进程清理 + 重连 | 3 个 mcp_server 进程，杀多余；改引擎源码后重连纪律不变（本轮起含 charter_check 面） |
| 3 | Mimosa 周期复扫 | 上次深扫 2026-09-17（25 findings 已 triage 于 `docs/mimosa-triage.md`）；锚 epoch/代码大变后建议复扫一次 |

## 明确不做（本阶段）

- 再按收割切片 bump minor（阶段切换仪式前版本钉 1.112.0）
- `chore: runtime state sync` / 产品仓直推运行态
- `EVOLVER_ACCEPTANCE_SHADOW=0`（三条件未齐，严禁转正）
- 本阶段 PyPI / 新 EvoX 切片 / RSI P2（多节点种群共享、soak 报告 v2、
  validator 安全模型深化、S30.3 发布决策——阶段后储备）
