# Self-Harness 演进 — 检查点 (Checkpoint 2026-08-09)

## 位置与分支

- **Worktree**: 已废弃（被外部清理器摧毁）。**当前工作在主仓库 `C:/GitHub/evolver.py`，分支 `self-harness`**（HEAD 已 checkout）
- **主仓库**: `C:/GitHub/evolver.py`（分支 `self-harness` = 所有工作所在）

> **检查点更新 3（C2 完成后）**：B1+A1+B2+C2 全部完成并提交。全部 8 个 Sprint 完成。回归 959 通过。

## ⚠️ 环境警告（关键，已更新策略）

外部定时任务约每 15 分钟执行 `git reset --hard HEAD` + `git clean -fd`，且**会摧毁 worktree 目录**（.git 链接、.venv、tracked 文件都会被删）。

**当前有效策略：主仓库 checkout `self-harness` 分支**：
- `reset --hard HEAD` → 恢复到 self-harness 最新提交 = **我的工作本身**（已提交，天然受保护）
- `.venv` 在主仓库 gitignored → `clean -fd` 不删 → 无需重装
- worktree 方式已废弃（目录会被毁）

**铁律：任何文件写入后立即 `git add` + `git commit`，再做测试。** 修复用后续提交。

## 已完成 (全部 8 个 Sprint，回归 959 通过)

| Sprint | 内容 | 里程碑提交 | 测试数 |
|---|---|---|---|
| **B1** | 因果诊断：`gep/diagnosis/{schemas,trace,causal,brief}.py` + `diagnosis_phase`（runner 插入 signals 后）+ flag `enable_diagnosis` | `448796c` | 76 |
| **A1** | 验收门：`gep/acceptance/{schemas,gate,t0_frozen,orchestrator,solidify_hook}.py` + solidify 接入 + `diagnosis_ref` in last_run + flag `enable_acceptance_gate` | `c669164` | 55 |
| **B2** | 跨用例聚类：`gep/diagnosis/clusters.py`（CausalSignature/Cluster/build/render）+ phase 集成（flag `enable_diagnosis_cluster`）+ artifact 含 clusters + prompt 注入 + `candidates.py` 因果簇候选 | `95cd2f8` 及 B2 wip 系列 | 19 |
| **C2** | 多提议者：`gep/multi_proposer.py`（Proposal/MultiProposerRequest + 逐槽生成 + 签名去重 + 重试≤2 + decline）+ `candidate_eval.pick_passing` + `dispatch_multi_propose_phase`（ROUTES>1 时输出多槽契约）+ config `MULTI_PROPOSE_ROUTES` | `0b639af` 及 C2 wip 系列 | 27 |
| 回归 | `tests/evolve tests/gep` 全绿 | — | 959 (688 基线 + 271 新增) |

### C2 新增文件/修改
- 新增：`src/evolver/gep/multi_proposer.py`、`tests/gep/test_multi_proposer.py`、`tests/gep/test_candidate_eval_passing.py`、`tests/evolve/pipeline/test_dispatch_multi_propose.py`
- 修改：`candidate_eval.py`（pick_passing）、`dispatch.py`（dispatch_multi_propose_phase）、`runner.py`（接入）、`pipeline/__init__.py`、`config.py`（MULTI_PROPOSE_ROUTES）
- 刻意省略（诚实范围）：候选材料化/逐候选验收门（属 A2/C3 集成）；routes>1 时仍打印 GEP prompt（双输出，外部 agent 用多槽契约）

### 新增文件清单

```
src/evolver/gep/diagnosis/__init__.py        # C-2: causal_* 命名
src/evolver/gep/diagnosis/schemas.py         # Criticality/TerminalFailureKind/StageRecord/CausalAnalysis
src/evolver/gep/diagnosis/trace.py           # 阶段切分（change 步骤）+ 终因分类
src/evolver/gep/diagnosis/causal.py          # LLM 归因（可注入 llm_call，严格 JSON 校验）
src/evolver/gep/diagnosis/brief.py           # markdown brief + root_cause signal 推导 (C-4)
src/evolver/evolve/pipeline/diagnosis.py     # diagnosis_phase（flag off = no-op）+ 落盘 (C-1)
src/evolver/gep/acceptance/__init__.py
src/evolver/gep/acceptance/schemas.py        # LayerKind/RepeatObs/LayerMetric/AcceptanceResult
src/evolver/gep/acceptance/gate.py           # decide() 泛化规则 + classify_rate/mean_of
src/evolver/gep/acceptance/t0_frozen.py      # 快照冻结 + pytest pass-rate 运行器
src/evolver/gep/acceptance/orchestrator.py   # baseline 建立/比较 + run_acceptance_gate
src/evolver/gep/acceptance/solidify_hook.py  # gate_for_solidify + gate_or_none（安全包装）
tests/gep/diagnosis/test_diagnosis_schemas.py  # 唯一 basename（避免 pytest 冲突）
tests/gep/diagnosis/test_trace.py
tests/gep/diagnosis/test_causal.py
tests/gep/diagnosis/test_brief.py
tests/evolve/pipeline/test_diagnosis_phase.py
tests/gep/acceptance/test_acceptance_schemas.py
tests/gep/acceptance/test_gate.py
tests/gep/acceptance/test_t0_frozen.py
tests/gep/acceptance/test_orchestrator.py
tests/gep/test_solidify_acceptance_hook.py
```

### 修改的被跟踪文件

- `src/evolver/config.py` — `DIAGNOSIS_INTERVAL/MAX_EVENTS`、`ACCEPTANCE_REPEATS/DELTA_EPSILON` + `__all__`
- `src/evolver/gep/feature_flags.py` — `enable_diagnosis`、`enable_acceptance_gate`（默认 False）
- `src/evolver/evolve/runner.py` — `diagnosis_phase` 插入 signals 后
- `src/evolver/evolve/pipeline/__init__.py` — 导出 `diagnosis_phase`
- `src/evolver/gep/solidify.py` — gate 接入（validation 后、event 前；拒绝→rollback）；`_apply_acceptance_gate` helper
- `src/evolver/evolve/pipeline/dispatch.py` — `last_run["diagnosis_ref"]` (C-1)

## 关键约束落实 (来自 §4.0 审计修正)

- **C-1** 进程边界：B1 产物落盘 `<gep>/diagnosis/<cycle>.json`；dispatch 写 `diagnosis_ref`；A1 gate 在 solidify 进程经 `gate_or_none` 读
- **C-2** 概念碰撞：产物名 `causal_*`（避开既有 `failure_diagnosis`）
- **C-4** select 钩点：root_cause 信号注入 `ctx["signals"]`（select 零改动）
- **C-5** flag 命名空间：布尔 → `EVOLVER_FF_*`/DEFAULT_FLAGS；阈值 → config.py

## 已知技术债（非我引入，勿动）

- `dispatch.py:127` F841 `artifact_path` 未使用（既有）
- `solidify.py` SIM105 try/except/pass ×2（既有）
- 仓库整体 ruff 861 / mypy 43 个既有错误（CI 声明 ≠ 实际基线）
- `test_solidify.py` 的 `git_ws` fixture 未断言 rollback 内容（既有盲点）

## 下一步（按修正后执行序）

**B2**（跨用例因果聚类）→ C2（多提议者）→ C3（AST 合并）→ A2（surface 解耦）→ C1（闭集钩子）→ D（LLM 模板）

B2 要点（见 SelfHarness演进方案_wikiskill对照版.md §4 Sprint B2）：
- `gep/diagnosis/clusters.py`：`CausalSignature`（terminal_cause/criticality/agent_mechanism 三元组）+ `build_causal_clusters` + 排序（CRITICALITY_RANK）
- `memory_graph` 存 `causal` 条目；`candidates._failed_capsule_candidates` 升级（B1 开启时用因果签名）
- prompt 注入因果簇简报段
- flag：`enable_diagnosis_cluster`（B2 关，默认 off）

## 恢复命令

```powershell
cd C:/Temp/opencode/evolver-sh
uv sync          # 已装好 .venv
uv run pytest tests/gep/diagnosis tests/gep/acceptance tests/evolve/pipeline/test_diagnosis_phase.py tests/gep/test_solidify_acceptance_hook.py -q   # 131 测试应全绿
git log --oneline | Select-Object -First 5   # 确认 HEAD=c669164 或之后
```
