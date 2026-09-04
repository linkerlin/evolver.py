# evolver.py 路线图（指针版）

> **本文件已冻结**：详细的差距清单、Sprint 回执与验收标准统一收敛到 **[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)**（单一真相源）。本文件仅保留当前状态指针，避免多份路线图互相矛盾（旧版仍锚 v1.89.14/v1.90.0，严重过时，已废弃）。

## 当前状态（2026-09-05）

- **对标基线**：Node evolver **v1.94.0**（master 1.x 线；v2.0.2 为独立 TS monorepo 线，评估见 演进方案_wikiskill对照版.md §9）
- **版本声明**：`pyproject.toml` **1.111.0**（v1.95+ 为 Python 线原生演进：蜂群/MCP 接管、HITL/HOTL、Hooks 双轨、技能桥、自适应变异、验收门 soak、YAML 工作流引擎）
- **测试规模**：**3455 用例全绿**（`-m "not llm"`；另 2 个 DeepSeek 活体 E2E 按 `-m llm` 门控）；`mypy src` strict **0 错误**
- **工程闸门**：`ruff check` / `ruff format --check` / `mypy src` strict 全绿
- **Dogfood（引擎吃自家狗粮）**：五轮真实仓库闭环跑通（round-1 `cb1c1d4` → round-5 `1bc35c3`）；验收门 gated_runs=**4**（verdict=collecting，需 ≥20 才可能 ready）；两工作流模板（repair/innovate）均已实战验证
- **EvoX 概念收割**：✅ 全部完成（评估反馈 E、HITL、HOTL、技能注册表、自适应变异率、DAG↔YAML 工作流）

## 剩余非阻塞项

| 项 | 优先级 | 说明 |
|---|---|---|
| 验收门样本积累 | 持续 | gated_runs 4/20；每轮 dogfood 自然积累；硬执法切换（`EVOLVER_ACCEPTANCE_SHADOW=0`）始终留人类决策 |
| v2 概念收割（cycle 状态机 / 事件保留） | 季度节奏 | 见 演进方案_wikiskill对照版.md §9 决策；UCB1 已于 Sprint 22.3 落地 |

## 演进（全部详见 演进方案_wikiskill对照版.md）

- 滚动审计版：2026-08-11（Sprint 20–21 完成）；蜂群弧线（v1.98–v1.111）见 CHANGELOG
- 历史：2026-07-31 / 07-29 / 07-17 / 07-06 / 06-20 / 06-15
