# 易用性改进（运行时数据外置）— 落地清单

> 对照 [`易用性演进方案.md`](易用性演进方案.md)，采用**一期兼容模式**（默认写入 `~/.evolver/workspaces/<id>/`，读取时若新路径不存在则 fallback 旧路径并告警）。不改 `frozen_gate` 基线语义，不默认 `skip_validation`，版本保持 **1.113.0**。

## P0 — 路径对齐与可诊断性

| # | 项 | 状态 | 落点 |
|---|---|---|---|
| U-1 | 启动解析（`evolver mcp --project` / `swarm_boot(project=...)`）与 `swarm_status` 必出 `repo_root`、`workspace_id`、`state_root`、`mismatch` | [x] 已完成 | `gep/paths.py`、`swarm.py`、`mcp_server.py`、`cli.py` |
| U-2 | `not_a_git_repo` 可执行诊断：附带 `suggested_actions`（`init_git_at` / `set_repo_root_to` 候选 git 子目录） | [x] 已完成 | `gep/paths.py`、`gep/solidify.py`、`swarm.py` |
| U-3 | 数据根强制外置：默认 `state_root=~/.evolver/workspaces/<id>`（`evolution/`、`gep/`、`hypothesis.json`、`meta.json`），一期支持旧路径只读 fallback 与告警 | [x] 已完成 | `gep/paths.py`、`gep/hypothesis.py`、`gep/solidify.py` |

## P0 — 固化失败可恢复

| # | 项 | 状态 | 落点 |
|---|---|---|---|
| U-4 | 回滚改 stash（`git stash push -u -m "evolver: rejected <run_id>"` + `rejected_stashes/` 补丁与未跟踪文件快照）与 `evolver solidify --restore-stash` 一键恢复 | [x] 已完成 | `gep/git_ops.py`、`gep/solidify.py`、`swarm.py`、`mcp_server.py`、`cli.py` |
| U-5 | 假说与 commit 同命运：仅 `solidify.ok == True` 时 `consume_hypothesis` 删除 `hypothesis.json`；失败轮經 `preserve_hypothesis_on_failure` 保留 `hypothesis.json`（免重登）并经 `stage_hypothesis` 保留 `prediction_delta` 计算能力 | [x] 已完成 | `gep/hypothesis.py`、`gep/solidify.py` |
| U-6 | `last_run` 防污染：pending 状态带 `run_id` + `updated_at` 原子替换；pytest 全局 autouse 强制临时 `EVOLVER_STATE_ROOT` | [x] 已完成 | `gep/solidify.py`、`tests/conftest.py` |

## P1 — 门禁分层与状态一张图

| # | 项 | 状态 | 落点 |
|---|---|---|---|
| U-7 | `validation_scope`：`related` \| `cascade` \| `skip`（`related` 强制校验 argv `list[list[str]]`，拒绝整串当命令名） | [x] 已完成 | `gep/solidify.py`、`swarm.py`、`mcp_server.py`、`cli.py` |
| U-8 | `env_blocker` 通道：与当前 diff 无关的红测、文件锁冲突或缺失未跟踪文档单独归入 `env_blockers`，门禁仍拒绝但报告与 `primary_score` 分层 | [x] 已完成 | `gep/solidify.py` |
| U-9 | `eval_worktree` 白名单与缺失文档清单：自动拷贝阶段文档（如 `*方案*.md`、`TODO*.md`）进评测树并输出 `overlaid_whitelist_docs` / `missing_untracked_docs` | [x] 已完成 | `gep/eval_worktree.py` |
| U-10 | `swarm_status.state_health`：evolution / hypothesis / gep / bench_baseline 四路路径存在性、同 `workspace_id` 与武装核验 | [x] 已完成 | `swarm.py` |
| U-11 | `evolver migrate-state`：将项目内 `memory/`、`.evolver/gep/` 与旧 soak 迁入 `~/.evolver/workspaces/<id>/` 并产出 `migration_report.json` | [x] 已完成 | `ops/migrate_state.py`、`cli.py` |

## P2 — 宿主体验糖与文档

| # | 项 | 状态 | 落点 |
|---|---|---|---|
| U-12 | `evolver round --host`：单入口串起协议步骤（boot → status → tick → checklist） | [x] 已完成 | `cli.py`、`swarm.py` |
| U-13 | `swarm_tick` 尾注 checklist：改哪里 → distill → hypothesis 模板 → solidify 前置 → feedback | [x] 已完成 | `swarm.py` |
| U-14 | 四语 README / AGENTS.md / CHANGELOG.md 与外置路径模型对齐，并由 `tests/test_usability_external_state_e2e.py` 全覆盖验证 | [x] 已完成 | `README*.md`、`AGENTS.md`、`CHANGELOG.md`、`tests/test_usability_external_state_e2e.py` |
