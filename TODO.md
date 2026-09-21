# evolver.py 工作清单

> 当前阶段章程：[`演进方案.md`](演进方案.md)（蜂群闭环稳定化，v1.112）。
> 长期差距 / Sprint 26–30 回执：[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)。
> RSI 分级路线：[`RSI演进对照.md`](RSI演进对照.md)（§五 实况审计、§六 effective-L5 实验）。
> Node 对标基线仍是 v1.94.0；Python 线版本见 `pyproject.toml`。

## 当前状态（2026-09-22，round-60 里程碑对账）

- 包版本：**1.112.0**（soak 封版中；「一阶段一 minor」，阶段切换留人类仪式）
- Dogfood：**60 轮**（round-35 回正后 26 轮连续环内干净运行）
- 测试：全套件 not-slow 级联全绿（~3730 passed；T0 分母 3653、基线
  0.999726 双重复一致）；ruff / mypy strict（330 文件）0 错误
- 验收门：`gated_cumulative=53`，滚动窗 20，**`verdict=unverified`**
  （round-49 两历史伪杀滑出后翻转；round-47 预演路径生产兑现），
  `verified_true_positives=0`（唯一转正阻塞——见 P1 #2），
  `interception=0.00`（健康安静期），shadow_mode=on
- 锚定评测：**Epoch 11 × 16 探针**，生产运行全绿（含「探针审判携带
  自身的变异」闭环 ×2）
- 环完整性：loop_integrity ok；周期相位遥测稳态 **0.07-0.11s**
  （hub 死端点三层修复后 118 倍归零；TTL 24h 重探 live 验证 3.2s
  落新天花板内）
- 运行态：外置 soak 根（30 命令路由白名单 + 亲和审计完成）；
  env 78/80；evidence/ 有界轮转（每周期路径）

## rounds 38-59 交付速览（自上轮对账）

- **P1 波次收口**（rounds 38-41）：cost/faithful 双口径 → recall 在库
  过滤 → 变体档案（DGM）→ K=2 种群前置段 + 锚 Epoch 11
- **端点健康弧线**（rounds 42-46, 49）：相位遥测 → hub 粘性 404 →
  hub_health 单咽喉 → 路由白名单（写者+读者 26 命令）→ 周期
  17.1s→0.145s（**118 倍**，DEBUG #45）
- **测试密闭性**（rounds 48, 54, 55）：hub 状态 + sniffer 状态 autouse
  防线（by-name 绑定陷阱）；30 模块运行态盘查；rounds 27-54 回溯
  覆盖 13 测（抓到 re-dispatch 解析真缺陷）
- **初始化即可用**（round-57，用户任务）：MCP instructions 自足
  bootstrap + next_action pending 感知 + supervision/hitl 渲染
- **死面收编**（rounds 56, 58, 59）：evidence/ 有界轮转（零读者死写者
  → 每周期路径接线）；lifecycle 近阈值段（39 基因 0 达阈值的结构事实）
- **effective-L5**：复跑 #3（round-43 捕获罐全空）+ #4（round-52
  verdict 翻转=修复-等待-兑现第二例）；跨纪元证据 **2/3**

## P1 — soak 转正路径（唯一剩余工作流）

| # | 项 | 内容与验收 |
|---|---|---|
| 1 | 环内继续攒干净样本 | cumulative 53 持续增长；纪律不变 |
| 2 | **人工登记首个 verified true positive**（人类动作·唯一阻塞） | 首个真实 T0 回归被门 shadow 拒绝且人工复核确认为真时：向 `$EVOLVER_HOME/anchor/gate-verifications.jsonl` 追加 `{"<event_id>": "confirmed"}`（verdict reason 已带完整指南） |
| 3 | 登记后的判定路径 | verified_tp≥1 后 verdict 走 `collecting_verified`（零拦截+人工背书=校准后安静期）；**最终 `ready` 需窗内出现带内拦截**——健康循环下可能长期不达，届时转正是人类对 `EVOLVER_ACCEPTANCE_SHADOW=0` 的直接判断（enforce_hint 一直这么写） |
| 4 | effective-L5 复跑 #5 | ~round-62 或捕获入账（判据 (a) 第三点仍待首个完整捕获：环境性拒绝→档案→重派→接受） |
| 5 | v1.112 收尾仪式（人类动作） | soak 判定落定后宣布阶段切换与下一 minor |

## Ops — 环境卫生（用户决定/顺手）

| # | 项 | 说明 |
|---|---|---|
| 1 | 守护进程处置 | pid 35664（Sep 7 round-7 代码）仍在循环——round-59 证实其存在使 cleanup 死接线（现已绕开）；建议 `evolver stop` 后按需 `evolver start`。**用户启动的进程，留用户决定** |
| 2 | MCP server 重连 | 重连后宿主即收到 round-57 自足 bootstrap 指令；陈旧孤儿进程清理 |
| 3 | Mimosa 复扫 | 2026-09-20 复扫 25 findings 与基线逐条全同（零新增）；下次大变更后再扫 |

## 明确不做（本阶段）

- 再按收割切片 bump minor（阶段切换仪式前版本钉 1.112.0）
- `chore: runtime state sync` / 产品仓直推运行态
- `EVOLVER_ACCEPTANCE_SHADOW=0`（verified TP 未登记，严禁转正）
- 本阶段 PyPI / 新 EvoX 切片 / RSI P2（多节点种群共享、soak 报告 v2、
  validator 安全模型深化、S30.3 发布决策——阶段后储备）
