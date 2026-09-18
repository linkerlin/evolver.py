# evolver.py 工作清单

> 当前阶段章程：[`演进方案.md`](演进方案.md)（蜂群闭环稳定化，v1.112）。
> 长期差距 / Sprint 26–30 回执：[`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md)。
> Node 对标基线仍是 v1.94.0；Python 线版本见 `pyproject.toml`。

## 当前状态（2026-09-18，round-33 交付）

- 包版本目标：**1.112.0**（稳定化封版中；上一发布 1.111.0）
- 测试：**3649 passed**（全套件 not llm，0 warnings）；ruff / mypy strict 0 错误
- 运行态：Dogfood 32 轮实测完成（round-1 ~ round-32）
- 验收门：`gated_cumulative=28`，滚动窗 `gated_runs=20`，`verdict=false_kill_high`，`verified_true_positives=0`，`shadow_mode=on`（数据不支持转正，保持 shadow 门控）
- 锚定评测：**Epoch 9**（14 冻结探针，涵盖判据可达性、门校准、遥测不变量、HITL fail-closed、数据入口守卫、基因生命周期等）
- 机制遥测：`ops/meta_report.py` Table-8 六维面板 + `library` 检索质量面板在线

## P0 — 蜂群稳定化闭环（已全部落地）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | 演进方案 + 本清单 | 完成 | 审阅结论落盘（演进方案.md §11） |
| 2 | 运行态出仓 | 完成 | gitignore `memory/` 运行文件 + `evolver/.config/`；保留 `LESSONS_LEARNED.md`；运行态零提交 |
| 3 | HITL 真门 | 完成 | mode 解析未知 fail-closed、损坏拒绝、skip 需 pending run、AUTO_HIJACK 强制 on |
| 4 | HOTL 包整引擎 | 完成 | pause/veto 进 `_run_single_cycle`；dispatch 前否决；solidify 拦截；实例锁；损坏视为暂停 |
| 5 | MCP 无人值守切断 | 完成 | AUTO_HIJACK 下拒绝 host 转达 approve/resume/unveto；destructive hint |
| 6 | 反馈机械 repair | 完成 | `swarm_feedback:degraded` / adaptive `repair_bias` → `force_category=repair` |
| 7 | 基因谱系 | 完成 | `landed_gene_id` 入事件/提交/冷却双罚 |
| 8 | 工作流门可审计 | 完成 | stdout+cwd+timeout；嵌套 park；模板写真话 |
| 9 | 杂项契约 | 完成 | skill `os.pathsep`；CLI distill hint；veto `--note`；过泛 veto 拒绝 |
| 10 | 发布卫生 | 完成 | 1.112.0；单一 Unreleased；`check_changelog.py` 严格校验 |
| 11 | 回归与补测 | 完成 | 全量 3583 passed；ruff / mypy strict 全绿 |
| 12 | RSI P0-1 锚定评测 | 完成 | `gep/anchor.py` + 仓外冻结探针（Epoch 6 × 11 探针），闭合自偏好漏洞 |
| 13 | RSI P0-2 机制遥测 | 完成 | `ops/meta_report.py` Table-8 六维面板 + 后代质量 + structural-L5 审计 |
| 14 | 退出判据重写 (round-30) | 完成 | 增 `gated_cumulative` + 仓外 `gate-verifications.jsonl`，解除安静期转正死锁 |

## P1 — 演进方案 §11.4 最新清单（收口与硬化）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | **T0 双侧重复** (P0-2) | 完成 | `orchestrator.py` 支持基线多重复与仲裁，触 T0 守卫面已升锚 **Epoch 7**（12/12 PASS） |
| 2 | `charter-check` 机器化回执 | 完成 | `evolver charter-check [--json]` 落地，全自动断言验收门/漂移/运行态卫生/锚纪元 |
| 3 | Worktree 默认开 | 完成 | `enable_eval_worktree` 转默认 ON；回退路径加固（脏运行态检测、明确 stderr 告警、strict 模式） |
| 4 | 仓外运行态强制互锁 | 完成 | 检测到 `inside_repo=true` 且非测试时自动路由至 `$EVOLVER_HOME/evolver.py-soak`；幂等资产种子迁移 + `charter-check --soak` 支持 |
| 5 | 数据入口清单 (P2) | 完成 | 半信任入口盘点；自由文本按占位符身份裸用即拒；文件通道规范；`enable_llm_template` 注册锚互锁；升锚 **Epoch 8**（13/13 PASS） |
| 6 | S29 机械提案通道 | 完成 | 结构化 Proposal 替代自由编辑 + distill：`swarm_propose` MCP 工具 + `solidify(proposal=...)` + CLI `--proposal` |
| 7 | S30.4/30.5 env/flag 退役 | 完成 | `EVOLVER_*` 变量从 180 收敛至 77（<= 80，`charter-check --soak` met=True） |

## P2 — RSI P1 波次（L2 跃迁主体，round-33 起）

> 次序依据 `RSI演进对照.md` §5.5：门校准 / effective-L5 对照 / 遥测 / 锚纪元
> 均已就地，此后按 P1-5 → P1-4 → P1-3 推进（先收束库质量，再交证据，
> 最后才开种群成本）。

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | 基因全生命周期治理 (P1-5) | 完成 | `gep/gene_lifecycle.py`：零后效→under_review→retired；选择器禁选/降权；`applicability` 硬门；CLI 人工复活；meta-report `library` 面板；**升锚 Epoch 9**（14/14 PASS） |
| 2 | 证据包派发 (P1-4) | 未动 | dispatch 失败侧证据包 + 提示词「干预提议」章节；S29 提案通道已就绪，两事合流 |
| 3 | 候选种群与谱系档案 (P1-3) | 未动 | K=2 worktree 并行（S26.5 桥已默认开）；成本翻倍需先补资源账口径 |

## 明确不做

- 再按收割切片 bump minor
- `chore: runtime state sync` / 产品仓直推运行态
- `EVOLVER_ACCEPTANCE_SHADOW=0`（当前 verdict=false_kill_high，未满足安全转正标准前严禁转正）
- 本阶段 PyPI / 新 EvoX 切片
