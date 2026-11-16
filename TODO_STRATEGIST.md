# Strategist 机械套具 — 落地清单

> 状态：**Tier 1–3 八项（`S-1`..`S-8`）与 Phase 2–3 工程/离线时间胶囊底座已落在工作区**（2026-11-16）。对照 *Strategist: Evolving Reasoning with Agents*（arXiv:2611.03618v1），遵循 [`演进方案.md`](演进方案.md)「算子即基因」总纲，不新增 `EVOLVER_*` 环境变量（守稳 `32 <= 35`），不切版本（保持 **1.114.0**）。

## Tier 1 — AST 结构去重、算子 DAG、受控沙盒与自动合成（`S-1` / `S-2` / `S-8b` / `P2-1` / `P2-2`）

| # | 项 | 精确落点 |
|---|---|---|
| S-1 | `OperatorGene.v1`（`operator_kind` / `builds_on` / `when_to_use` / `lens` / `codemod` / `invariant` / `structural_hash` / `slot_specs` / `slot_bindings`）；AST `structural_hash` 剥离 `META`/docstring/字符串常量并保 f-string 占位符拓扑；`s1..sk` 运行期槽位覆写；`deduplicate_or_bind_operator` 接入 `operator_synthesizer` 与 `distill.install_distilled` | `gep/schemas/gene.py`、`gep/sync_asset.py`、`gep/operator_slots.py`、`gep/distill.py` |
| S-2 | `composed` 算子 DAG 组合（经 `ctx.call_lens` 嵌套调用，深度上限 4）；`audit_operator_ast` 与 `detect_operator_dag_cycle` 校验 `builds_on` / `ctx.call_lens` 一致性、拦截未声明调用、孤岛声明、已退役依赖与环路 | `gep/operator_sandbox.py`、`gep/lenses.py` |
| P2-1 | 零网络只读受控沙盒（拦截危险导入/写操作/动态执行，剥离凭证，`< 2s` 线程超时 + 子进程不变量探针）；清理 `genes.seed.json` 旧 `node` 验证串，补齐 8 颗经本仓真 Bug 淬炼的 Python `op_*` 种子算子（含组合算子 `op_traceback_blast_audit`） | `gep/operator_sandbox.py`、`assets/gep/genes.seed.json` |
| S-8b | 反投机作弊静态审计门（拦截 `pytest.skip`/`xfail`、伴随 `src/` 改动的删测、断言弱化为 `assert True/pass` 与任务编号硬编码查表），接入 `solidify` 在验收前转为 `draft_preserved` 软拦停 | `gep/policy_check.py`（`detect_anti_cheat_violations`）、`gep/solidify.py` |
| P2-2 | 红转绿零干预算子自动合成器：在 `evolve_settle` 成功归因 `helped` 后提炼候选 `OperatorGene.v1`，依次过防作弊门、AST 安全门、正负自检、隔离不变量探针、`H2-2` 脱敏门与 `S-1` AST 折叠入库（同构归并 `+0` 克隆膨胀）；触发 `gene_lifecycle.evaluate_and_apply` | `gep/operator_synthesizer.py`、`gep/skill2gep_audit.py`、`swarm.py` |

## Tier 2 — 双视图混合检索、动态测量卡与差量自照镜（`S-3` / `S-4` / `S-7`）

| # | 项 | 精确落点 |
|---|---|---|
| S-3 | 双视图混合检索：结构词法 IDF（`0.4`，并修正 `selector.tokenize` ASCII 大写转小写缺陷）+ 实测经验 3-gram/token 向量（`0.6`，PID 原子缓存于 Windows/POSIX）；`retrieve_operators_and_inspiration` 产出零重合跨家族邻域灵感（ranks 4..12） | `gep/hybrid_retrieval.py`、`gep/selector.py`、`gep/index_db.py` |
| S-4 | 动态算子测量卡（引擎事实栏读自 `index.sqlite`，经验笔记过 `is_concrete_experience_note` 滤虚空话并过 `val_seal.redact`）；`dedupe_seen_cards` 会话级折叠已见卡/差量更新；组合前检查 `audit_cards_read_before_compose`；`run_lens(name="card")` 接入 | `gep/operator_cards.py`、`gep/lenses.py`、`gep/prompt.py`、`evolve/pipeline/select.py` |
| S-7 | `multi_proposer` 局部槽位差量修补（`build_slot_repair_prompt` / `merge_proposal_patch` 支持 `replace_slots`/`set_fields`）；`blackbox.classify_patch_mechanisms` 与 `render_mutation_structure_mirror` 生成单行同构失败自照镜注入 GEP 提示词（`< 3800` tokens） | `gep/multi_proposer.py`、`gep/blackbox.py`、`gep/prompt.py`、`evolve/pipeline/dispatch.py`、`swarm.py` |

## Tier 3 — 帕累托配对统计、方向反馈防过拟合、分档路由与双源时间胶囊（`S-5` / `S-6` / `S-8a` / `P3-1` / `P3-2`）

| # | 项 | 精确落点 |
|---|---|---|
| S-5 | 双路径配对通过率—成本帕累托裁决 `compare_paired_pareto`（McNemar 精确检验 + Delta 法比值 SE + 对数几何均值防极值离群失真 + 按内/外源切片细分），识别 `quality_win` / `efficiency_win` / `keep_baseline` 并接入 `experiment/comparison.py` | `bench/compare.py`、`experiment/comparison.py` |
| S-6 | `direction_envelope_for_host` 与 `swarm._attach_host_direction` 对宿主隐藏四位小数原始分值、仅反馈噪声带定性方向；`val_seal.sealed_secrets()` 同步密封已安装的 `capsule_v2.json` `hidden_select` 与 `sealed_test` 题面/测试代码 | `bench/frozen_gate.py`、`swarm.py`、`gep/val_seal.py` |
| S-8a | 激活休眠字段 `Gene.routing_hint`：`compute_routing_advice` 按 `1 : 2.83 : 6.67` 算力权重并在连败 $\ge 2$ 时自动升档，经 `evolve_begin`、`proxy/router/model_router.py` 与 `experiment/agent_runner.py` 贯彻端到端计量 | `gep/router.py`、`proxy/router/model_router.py`、`experiment/agent_runner.py`、`swarm.py` |
| P3-1 / P3-2 | 36 题双源离线 Python Time-Capsule（16 内源 `DEBUG.md` + 16 外源 OSS 模式 + `dev_feedback` + `hidden_select`）；`--install-time-capsule` 仓外安装与 `--stage-exit-v2` AB/BA 交错真实 `pytest` 盲测裁决报告（`report.json` + `per_task_results.jsonl`）；实装真实编码 LLM `--stage-exit-v2` 尚待宿主/操作者按需凭真实 API 触发 | `experiment/time_capsule.py`、`experiment/cli.py` |

## 验收

`tests/gep/test_strategist_tier1_operators.py`、`tests/gep/test_strategist_tier2_retrieval_cards.py`、`tests/experiment/test_strategist_tier3_pareto_capsule.py`、`tests/test_selector.py`、`uv run ruff check src tests`、`uv run ruff format --check src tests`、`uv run mypy src`、`uv run evolver internal charter-check`（`32 <= 35`）与 `uv run pytest -m "not slow"` 全部通过。
