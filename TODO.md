# evolver.py 路线图（指针版）

> **本文件已冻结**：详细的差距清单、Sprint 回执与验收标准统一收敛到 **[`演进方案.md`](演进方案.md)**（单一真相源）。本文件仅保留当前状态指针，避免多份路线图互相矛盾（旧版仍锚 v1.89.14/v1.90.0，严重过时，已废弃）。

## 当前状态（2026-08-11）

- **对标基线**：Node evolver **v1.94.0**（master 1.x 线；v2.0.2 为独立 TS monorepo 线，评估见 演进方案.md §9）
- **版本声明**：`pyproject.toml` **1.94.0**（行为等价 v1.94.0）
- **测试规模**：**3002 用例全绿**（无 --ignore 排除；Node ~3215 的 ~93%）
- **工程闸门**：`ruff check` / `ruff format --check` / `mypy src` strict 全绿
- **Sprint 1–21 全部完成**：v1.94.0 六项增量（sandbox 加固 / publish 验证闸 / Claude 上下文基因家族 + seed 升级 / feedbackEnvelope / 12 上下文膨胀信号 / ssePlannedClose）+ a2a 契约 55 用例 + solidify 助手 + distiller meta 门 + event_delivery daemon E2E + 基线清偿（ruff 885→0 / mypy 44→0）+ 发布（CHANGELOG/README）+ v2 评估

## 剩余非阻塞项

| 项 | 优先级 | 说明 |
|---|---|---|
| ja/ko README 扩展 | P3 | 当前为纯命令 stub（无过期指针，非伪 stub） |
| G8 余项 | P3 | internal-proxy-env 脚本 + PR 模板 + CI 版本断言 ✅ 已完成；hosted-runner 天然满足 |
| v2 概念收割（UCB1 / cycle 状态机 / 事件保留） | 季度节奏 | 见 演进方案.md §9 决策 |
| 全量测试提速（`-m "not slow"` 分轨） | P3 | 3000+ 用例 ~14 分钟 |

## 演进（全部详见 演进方案.md）

- 滚动审计版：2026-08-11（Sprint 20–21 完成）
- 历史：2026-07-31 / 07-29 / 07-17 / 07-06 / 06-20 / 06-15
