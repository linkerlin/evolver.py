# evolver.py 工作清单

> 当前阶段章程：[`演进方案.md`](演进方案.md)（蜂群闭环稳定化，v1.112）。
> 长期差距 / Sprint 26–30 回执：[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)。
> Node 对标基线仍是 v1.94.0；Python 线版本见 `pyproject.toml`。

## 当前状态（2026-09-05）

- 包版本目标：**1.112.0**（稳定化；上一发布 1.111.0）
- 测试：3469 passed（`-m "not slow and not llm"`）；ruff / mypy strict 全绿
- Dogfood：五轮已跑通；验收门 gated_runs=**4**/20，verdict=`collecting`，**不转正**
- 本阶段不做新的 EvoX 收割、不扩 CLI/MCP 表面

## P0 — 本阶段必须做（稳定化）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | 演进方案 + 本清单 | 完成 | 审阅结论落盘 |
| 2 | 运行态出仓 | 完成 | gitignore `memory/` 运行文件 + `evolver/.config/`；保留 `LESSONS_LEARNED.md`；`git rm --cached` |
| 3 | HITL 真门 | 完成 | mode 解析、损坏 fail-closed、skip 需 pending run、审批进 `solidify()`、AUTO_HIJACK 强制 on |
| 4 | HOTL 包整引擎 | 完成 | pause/veto 在 `_run_single_cycle`；dispatch 前否决；基因 id 再挡 solidify；实例锁；损坏视为暂停 |
| 5 | MCP 无人值守切断 | 完成 | AUTO_HIJACK 下拒绝 approve/resume/unveto；destructive hint；instrument 资源无副作用 |
| 6 | 反馈机械 repair | 完成 | `swarm_feedback:degraded` / adaptive `repair_bias` → `force_category=repair` |
| 7 | 基因谱系 | 完成 | `landed_gene_id` 入事件/提交/冷却 |
| 8 | 工作流门可审计 | 完成 | stdout+cwd+timeout；嵌套 park；模板写真话 |
| 9 | 杂项契约 | 完成 | skill `os.pathsep`；CLI distill hint；veto `--note`；过泛 veto 拒绝 |
| 10 | 发布卫生 | 完成 | 1.112.0；单一 Unreleased；`check_changelog.py` 拒绝多个 |
| 11 | 回归 | 完成 | 3469 passed（not slow/llm）；ruff / mypy 全绿 |

## 回执跟进（§9.4 → §9.5，已做）

- DEBUG.md #12 自批自恢、#13 归因错位；#9 标 v1.112.0
- CHANGELOG Upgrade notes（`HITL_MODE=disabled` 现为 on）
- `演进方案.md` 移出 gitignore，公开链接可入库
- soak 运行门写法见 演进方案.md §10

## P1 — 下一阶段（soak，不在 1.112 宣称完成）

| 项 | 说明 |
|---|---|
| 外置 EVOLUTION_DIR 把 gated_runs 跑到 20 | 工具已就绪：`evolver soak setup/exports/status`；同一版本 1.112.0 实跑；禁止提交 memory/；人类再决定 SHADOW=0 |
| S26.5 干净 worktree 跑门 | 引擎已落地（flag 默认关）；soak 时 `EVOLVER_FF_ENABLE_EVAL_WORKTREE=1` |
| S30.4/30.5 env/flag 退役 | 252 → ≤80 |
| 拆 `swarm/` 包 | 阻止 `swarm.py`/`cli.py` 继续膨胀 |
| S29 机械提案作宿主默认路径 | 替代自由编辑 + distill |
| Validator 安全模型 | 仍约 50% |
| `enable_event_history` 转默认 | 冷却已不依赖；打开需单独 soak |

## 明确不做

- 再按收割切片 bump minor
- `chore: runtime state sync` / 产品仓直推 `evolver: gene_*`
- `EVOLVER_ACCEPTANCE_SHADOW=0`（样本不够）
- 本阶段 PyPI / 新 EvoX 切片
