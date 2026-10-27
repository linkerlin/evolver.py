# Harness2 机械套具 — 落地清单

> 状态：**六项已落在工作区**（2026-10-26）。对照 arXiv:2610.14224v1（*Harness2: Recursive Agent Harnessing for an Open World*），不替换 [`演进方案.md`](演进方案.md) 的「经验即证据」出口，不改 `frozen_gate`，不切版本（保持 **1.113.0**）。
> 记录分层与调用图钉不变：`attribution` 与 `behavioral_contrast` 均由引擎自记（`source="engine"`），宿主上报与 `WORKING_SESSION.md` 仍作线索、不进验收维。

## Tier 1 — 组件级四值归因与防过拟合经验协议

| # | 项 | 完成时 |
|---|---|---|
| H2-1 | 组件级四值归因（`helped \| hurt \| no_observed_effect \| confounded`）与混杂编辑过滤门：多组件同时编辑且无独立隔离执行证据时强制标 `confounded`（`eligible_for_experience=False`）；`render_episode_block` 仅在 `gates.attribution` 存在时多一行，旧记录逐字节不变，`dispatch.py` 经 `attribution_note` 按需追加提示行；`install_distilled` 与 `swarm_distill` 自动拦截混杂轮的持久基因落库 | `gep/episode_record.py`（`compute_component_attribution` / `attach_component_attribution` / `attribution_note`）、`evolve/pipeline/dispatch.py`、`gep/distill.py`、`swarm.py` |
| H2-2 | 可迁移经验三元组契约（`cue + lesson + evidence` / `NO_ENTRY`）与 `in this workspace:` 局部事实物理隔离门：局部事实写入 `WORKING_SESSION.md` 并在会话结束时物理 `unlink`；审计器与 `evolver distill --strict-transferable` 自动拦截含 `in this workspace`、临时沙箱路径、评测题号、裸行号锚点的持久基因候选 | `gep/working_memory.py`（`format_workspace_facts_section` / `extract_workspace_facts`）、`gep/skill2gep_audit.py`（`audit_workspace_fact_leakage` / `validate_transferable_experience`）、`cli.py` |

## Tier 2 — 正交作用域提案、机械选择性合成器与组件成本层级门

| # | 项 | 完成时 |
|---|---|---|
| H2-3 | `INV × DOM` 正交作用域提案与机械选择性合成器（`compose_proposals`）：`INV`（`capability` / `dimension="tool"`）负责 `scripts/`、`plugin/`、工具面；`DOM`（`adaptive` / `dimension="content"`）负责领域规则、交付物契约、领域 Skill；`compose_proposals`（已接入 `swarm_propose`、`solidify(proposal=...)` 与 `evolver apply-proposal`）过滤 `hurt`/`confounded`/`non_delivering` 与越界编辑，按锚点无冲突合并或退回 `KEEP_BASE`（`action="no_action"`），并在 `evolver variants` 中支持 `salvageable_semantic_variants` 跨轮捞回干净单组件编辑 | `gep/record_route.py`（`validate_proposal_scope` / `build_scoped_direction_prompt`）、`gep/proposal.py`（`compose_proposals`）、`gep/variant_archive.py`（`salvageable_semantic_variants`）、`gep/solidify.py`、`swarm.py`、`cli.py` |
| H2-4 | 组件成本层级（`Skill > Script > Subagent > Hook > Always-On Text`）与提案前三条静态契约门：① Skill YAML frontmatter `name:` 与目录名一致、具备 `description:` 且在常驻文件中可达；② 引用的 `scripts/<name>.py` 存在且通过 `ast.parse()`；③ 常驻文件无裸模板花括号 `{{`/`{%` 且净增超 `MAX_ALWAYS_ON_NET_GROWTH_CHARS` 时告警下沉 | `gep/policy_check.py`（`validate_harness_component_integrity` / `COMPONENT_COST_HIERARCHY`）、`swarm.py` |

## Tier 3 — 行为对比遥测、交付物六维合规与双层递归库溯源

| # | 项 | 完成时 |
|---|---|---|
| H2-5 | 行为对比遥测（`compute_behavioral_contrast` / `behavioral_contrast_note`）与交付物六维形状合规校验（`check_deliverable_conformance`）：追踪 `newly_passed`/`regressed`/`persistent_failed` 检查跃迁、`tool_error_delta` 与 `non_delivering` 并经 `dispatch.py` 跨轮动态追加提示行；校验 `delivery`、`conformance`、`fidelity`、`internal_consistency`、`operational_fitness`（拦截未求值公式 `=SUM(`/`#REF!`）与 `finish`（拦截 `TODO`/`TBD`） | `gep/episode_record.py`（`compute_behavioral_contrast` / `attach_behavioral_contrast` / `behavioral_contrast_note`）、`evolve/pipeline/dispatch.py`、`gep/policy_check.py`（`check_deliverable_conformance`） |
| H2-6 | 双层递归（$\mathcal{H}^{(t)} = \mathcal{H}_0 \cup \mathcal{R}_t$）配对求解装配与 `library_provenance` 遥测面板：`prepare_paired_library_solves` 每次重置任务沙箱回 $\mathcal{H}_0$，分别绑定 Parent 快照与 `save_version` 候选快照生成提示词并校验 `solve_receipt.v0`（`active.json` 不动）；`meta_report.py` 与 `evolver meta-report` 闭合 `direct_copy` / `adapted` / `novel` 库来源率与分类成功率面板 | `bench/runner.py`（`prepare_paired_library_solves` / `verify_solve_receipt`）、`ops/meta_report.py`（`library_provenance_panel`）、`cli.py` |

## 验收

`uv run ruff check src tests`、`uv run ruff format --check src tests`、`uv run mypy src`、`uv run pytest tests/gep/test_harness2_mechanisms.py`、`uv run pytest tests/test_auto_trigger_and_evolution_e2e.py` 及仓外 `uv run evolver anchor run`（epoch 13, 17/17 PASS）全部通过。
