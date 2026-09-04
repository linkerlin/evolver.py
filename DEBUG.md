# DEBUG.md — 修复经验簿

> dogfood 五轮（round-1~5）与补测会话真实修复之 bug 清单。每条记**症状 → 根因 → 修复 → 可迁移经验**。
> 新会话排障时先查此簿；修完新 bug 须回填。

## 总览

| # | 缺陷 | 层 | 轮次 | 版本 |
|---|---|---|---|---|
| 1 | 运行态文件混入变异提交（爆炸半径 3→42 虚胖） | solidify | round-1 | v1.108.0 |
| 2 | 裸 venv python 下验证级联全跳过（unvalidated success） | solidify | round-1 | v1.108.0 |
| 3 | 15 个存量 mypy 平台错误卡死所有 gated run | 全仓 | round-2 | v1.109.0 |
| 4 | 测试直读宿主仓库真实状态（宿主相关失败） | tests | round-2 | v1.109.0 |
| 5 | 降级周期白烧一整个进化 tick（首 tick 延迟） | dispatch | round-3 | v1.110.0 |
| 6 | 蒸馏静默零产出（宿主无从自纠格式） | swarm_distill | round-4 | v1.110.1 |
| 7 | 选择器反复重派已落地基因 | selector | round-5 | v1.111.0 |
| 8 | 冷却死代码（flag 默认关致事件尾永不加载） | selector | round-5 | v1.111.0 |
| 9 | `complete_agent` 无视失败契约（`ok: False` 照常推进） | workflow | 补测 | 未发版 |
| 10 | 技能基因哈希失配被静默丢弃 | skill_assets | v1.104 | v1.104.0 |
| 11 | solidify 回滚 stash 重放陷阱 | 运维 | round-2 | 运维经验 |

## 条目

### 1. 运行态混入变异提交（round-1）

- **症状**：`solidify` 报告爆炸半径 42 文件，变异本体只动了 3 个。
- **根因**：`_commit_mutation` 把守护进程实时写的 `memory/`、`.evolver/`、
  `evolver/.config/` 全部 stage——引擎自己的运行痕迹污染了自己的变异审计。
- **修复**：`_is_runtime_state(rel)` 过滤，提交目标与爆炸半径计算共用同一过滤。
- **经验**：**自观测数据永远不得进入被观测对象的变更集**。凡引擎「提交工作区」类
  功能，先问：哪些文件是引擎自己在写的？

### 2. 裸 venv 下级联全跳过（round-1）

- **症状**：solidify `success` 但 `gated_runs` 不增——三阶段全部 `skip`。
- **根因**：PATH 无 ruff/mypy/pytest 时级联命令解析失败 → 静默跳过 → 无验证即通过。
- **修复**：`get_fitness_cascade_commands` 回退 `<sys.executable 目录>/工具`；
  子进程级测试清洗 PATH 复现真实场景。
- **经验**：**「跳过」与「通过」语义必须可区分且默认从紧**——静默降级的安全机制
  等于没有机制。unvalidated success 是验收门最危险的假绿。

### 3. 存量 mypy 平台债卡级联（round-2）

- **症状**：级联首次真实执行 mypy 即挂 15 个错误（winreg/windll/creationflags 等
  Windows-only 属性）——此前从未暴露，因为级联从未真正跑过（见 #2）。
- **修复**：统一 `getattr(module, name, default)` 惯用法（运行时零变化）；
  删除 4 处已漂移的 unused-ignore。
- **经验**：**修复一个静默降级会暴露其下游积压的全部债务**——预算上要预期连锁；
  跨平台属性一律 getattr，不写平台条件 type: ignore（会在另一平台变 unused-ignore）。

### 4. 测试直读宿主状态（round-2）

- **症状**：`test_repair_loop_circuit_breaker_empty` 在真仓里 `consecutive == 2` 失败。
- **根因**：未隔离 `GEP_ASSETS_DIR`，读到了宿主仓库真实的 repair+failed 事件。
- **修复**：补 `monkeypatch.setenv` 隔离（同 `conftest.temp_workspace` 模式）。
- **经验**：**凡读状态文件的测试必须显式隔离路径环境变量**——dogfood/真仓运行
  会让「本地绿」变「宿主红」。AGENTS.md 坑阱篇早有此训，仍被漏——排障时先查隔离。

### 5. 降级周期白烧 tick（round-3）

- **症状**：注入信号后需 2 个 tick 才 dispatch；首个 tick 报 `idle_cycle`。
- **根因**：`dispatch_phase` 把「跳过 Hub 调用」与「跳过本地 dispatch」混为一谈
  ——Hub 降级标志被消耗的那个 tick，即便基因已选中也不出提示词。
- **修复**：按 `hub_skip_reason` 分裂语义：饱和稳态（无理由）保持 idle；
  `autopoiesis_degraded` / `preflight_abort_recovery` 仍本地 dispatch。
- **经验**：**一个布尔位承载两种语义时，先拆语义再修行为**。实证方法：
  设标志 + 单 tick 直击修复路径，对照修复前后 `dispatch_reason`。

### 6. 蒸馏静默零产出（round-3/4）

- **症状**：`swarm_distill` 返回 `genes: 0` 且 `errors: []`——宿主不知格式错在哪。
- **根因**：纯文本响应无 ```json 块时零提取属正常路径，但无任何指引；
  另有 `Gene.category` 枚举陷阱（`"innovation"` 非法，合法值
  `repair|optimize|innovate|explore`）。
- **修复**：零资产时附 `hint`（期望块形状 + 合法枚举）+ `next_action=
  resubmit_with_asset_blocks`；坏块时 errors 与 hint 并列。
- **经验**：**人机接口的「空结果」必须携带「如何不空」**；同族陷阱：
  `EvaluationFeedback.metrics` 只收 `dict[str, float]`（字符串值直接 ValidationError）。

### 7. 选择器重派已落地基因（round-5）

- **症状**：round-3/4 的 tick 反复选中 round-1/2 已固化的基因（同信号仍在语料、
  同基因仍最佳匹配），每次浪费一个完整周期。
- **修复**：近窗成功固化基因 ×0.25 惩罚（非禁选：唯一匹配仍可选）；
  `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` / `_PENALTY` 可调。
- **经验**：**重复选中所以内聚地发生，是因为状态（已应用）没进决策输入**——
  排障顺序：先确认决策函数看得见哪些状态，再调权重。

### 8. 冷却死代码（round-5，藏在 #7 之下）

- **症状**：惩罚实现后实证仍选旧基因——两段式根因。
- **根因**：事件尾取自 `ctx["recentEvents"]`，而该键由 `enable_event_history`
  （默认 **False**）控制加载——flag 关时冷却永不触发；且窗口被 `x1` 类簿记噪音
  事件稀释（先过滤有效事件再取窗修复）。
- **修复**：冷却自取事件尾（与 flag 解耦）；窗口只计带 outcome 的 mutation 事件。
- **经验**：**依赖注入键若由别的 flag 决定存在性，新消费者必须自取或显式断言**。
  三段实证（噪音稀释 → flag 根因 → 决定性通过）是此类「改了但没生效」的标准解法。

### 9. complete_agent 失败契约失效（补测会话）

- **症状**：新测试断言失败任务应使 run 失败，实际却推进到 `waiting_approval`。
- **根因**：`complete_agent` 不看结果内容——CLI `--fail` 与 swarm complete 的
  失败语义形同虚设。
- **修复**：dict 结果携带 `ok: False` 即失败该 run（WAL 记 `agent_failed`），
  与 approval/gate 失败语义对齐。
- **经验**：**外部报告的失败必须成为状态机转移**。补测方式：覆盖审计
  （`pytest --cov`）找冷分支 → 写「应然」测试 → 暴露「实然」缺口。

### 10. 技能基因哈希静默丢弃（v1.104）

- **症状**：`skills sync` 后基因入库但加载时「消失」。
- **根因**：skill2gep 本地哈希公式（repr 基）≠ asset_store 规范化哈希；
  `load_genes()` 对哈希失配静默跳过（防篡改设计，但也吞掉了集成错误）。
- **修复**：`sync_skills` 用 `compute_asset_id` 重算。
- **经验**：**内容寻址系统的写入方必须复用读取方的哈希函数**；两处「各自正确」
  的实现对接时，哈希是首个断言点。

### 11. solidify 回滚 stash 重放（运维，round-2）

- **症状**：solidify `validation_failed` 后变异消失；stash 列表有 "evolver rollback"
  但 `git stash pop` 既保留条目又不还原文件。
- **修复（操作法）**：`git checkout 'stash@{N}' -- <files>` 可靠重放；事后 drop
  全部相关 stash（变异可能在 `stash@{1}` 而非 `stash@{0}`——memory 运行态与源码
  混在相邻两个 stash 里）。
- **经验**：**引擎回滚产物的重放永远用 checkout，不用 pop**。

## 方法论沉淀

1. **覆盖审计先行**：`pytest --cov` 找冷分支再补测——#9 由审计钓出，非偶然。
2. **实证闭环**：每修必跑「根因场景」对照（设标志/造输入 → 修复前后行为差）；
   改了但没生效时，怀疑注入链上有 flag/噪音两层。
3. **静默降级是头号嫌疑**：skip/unvalidated/empty 且无指引的路径，六个 bug 里
   四个（#2/#6/#8/#10）生于静默。
4. **真仓即试验场**：dogfood 让 #1/#4/#5/#7 只可能在真实运行中现形——单测全绿
   不等于引擎能用。
