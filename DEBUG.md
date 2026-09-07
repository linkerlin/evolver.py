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
| 9 | `complete_agent` 无视失败契约（`ok: False` 照常推进） | workflow | 补测 | v1.112.0 |
| 10 | 技能基因哈希失配被静默丢弃 | skill_assets | v1.104 | v1.104.0 |
| 11 | solidify 回滚 stash 重放陷阱 | 运维 | round-2 | 运维经验 |
| 12 | MCP 宿主可自批 skip / 自恢复监督 | hitl/hotl | 审阅 | v1.112.0 |
| 13 | 固化提交与冷却记剧本基因、不记落地基因 | solidify/selector | round-4 实证 | v1.112.0 |
| 14 | MCP 探针单通道解包致工具面全 FAIL（假阴性） | 测试工具 | MCP 接入 | 运维经验 |
| 15 | 探针断言口径三处错（假阴性第二批） | 测试工具 | MCP 接入 | 运维经验 |
| 16 | venv 旧模块疑虑 + stdio 长驻进程不重载 | 部署 | MCP 接入 | 运维经验 |
| 17 | 工具面缺两个：配置/服务端/客户端三层排查 | 部署 | MCP 接入 | 运维经验 |
| 18 | `asset_search` 多词必空 + summary/signals 不入检索 | mcp_server | 工具体检 | 未发版 |
| 19 | 重复固化烧级联 + 幻影成功事件污染 soak 样本 | solidify | round-12 | 未发版 |
| 20 | 谱系链测试假设同 run 双固化（与 #19 守卫冲突） | tests | round-12 | 未发版 |

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

### 12. MCP 宿主自批 skip、自恢复监督（v1.112 审阅）

- **症状**：文档写 HITL/HOTL 是人类门；MCP 工具 `swarm_approval_resolve` /
  `swarm_supervise(resume|unveto)` 默认 `by=human-via-host`，无人值守宿主
  可自己批准 `skip_validation`、自己解除暂停。
- **根因**：审批与监督被做成「宿主转达」而非带外通道；instrument 写「先问人」
  只是提示词。`EVOLVER_HITL_MODE=ON`/`disabled` 也不等于 on（大小写/未知值
  静默保持 off）。
- **修复**：`parse_hitl_mode`（未知 fail-closed 为 on）；`AUTO_HIJACK=1` 强制
  HITL 且拒绝 MCP 转达的 approve/resume/unveto（改走 CLI）；pause/veto 进入
  `_run_single_cycle`；损坏的状态文件 fail-closed。
- **经验**：**「请先问人」不是门**。凡高危动作，默认关闭的审批 + 同一 stdout
  上的转达工具 = 宿主既是申请者也是批准者。无人值守必须切断转达或另开通道。

### 13. 提交说明与冷却罚错基因（round-4 实证，v1.112 修）

- **症状**：git 提交 `d68a7fc` 报 `gene_hub_fetch_resilience`，实际改的是
  distill 格式提示（蒸馏基因为 `gene_distill_format_hint`）。冷却窗口跟着
  剧本 id 走，罚错对象。
- **根因**：`_commit_mutation` 与冷却只读 `selected_gene_id`（dispatch 选出的
  剧本）。宿主按剧本改树后 distill 出的新基因从未写回事件。
- **修复**：`swarm_distill` 把落地 id 写入 solidify state；事件同时带
  `gene_id` 与 `landed_gene_id(s)`；提交说明优先落地基因；冷却对两类 id 都罚。
- **经验**：**决策输入、审计输出、冷却键必须是同一标识**。历史 round-1~5
  事件只有剧本 id——冷却对旧事件会天然失效一个窗口，属预期成本，不必回填。

### 14. MCP 探针单通道解包致工具面全 FAIL（MCP 接入，2026-09-05）

- **症状**：stdio 烟测 22 项里 8 项工具面检查全 FAIL（返回 None），协议面
  （initialize/resources/prompts）却全过——疑服务端工具坏。
- **根因**：探针只读 `structuredContent`；该构建下服务端把 dict 结果序列化为
  `content[0].text` JSON（pretty-printed）且不带 structuredContent 字段。
  后经 ZCode 客户端实际连接发现两通道皆有——通道可用性随客户端能力协商
  而异，探针写死了单一假设。
- **修复**：双通道解包——优先 `structuredContent`（含 `{"result": ...}` 解包），
  退化为 `json.loads(content[0].text)`。
- **经验**：**测试工具自身的 bug 会伪装成被测物的全面故障**。协议面过、
  数据面全挂这种「一刀切」的失败模式，先怀疑探针的解包/断言层，再怀疑服务。
  另：裸 `timeout` 管道在 macOS 静默无输出（无 GNU coreutils），子进程超时
  用 Python `communicate(timeout=)`。

### 15. 探针断言口径三处错（MCP 接入，2026-09-05）

- **症状**：解包修复后仍 3 项 FAIL：approvals / supervise status /
  AUTO_HIJACK approve 阻断。
- **根因**：三处断言与实现口径不符——`swarm_approvals` 返回 `{pending,
  recent}`（非 `requests`/`ok`）；`swarm_supervise` 的 state 嵌套于
  `supervision.state`；`swarm_approval_resolve` 的参数是 `approve: bool`
  而探针传了 `decision:`（approve 默认 False → 阻断分支自然不触发）。
- **修复**：按真实返回键形与参数名修正断言，22/22 全过。
- **经验**：**写断言前先抓一次原始响应**（raw dump），别凭记忆写键名。
  布尔参数传错名是静默的：默认值让调用「成功」却测不到目标分支。

### 16. venv 旧模块疑虑 + stdio 长驻进程不重载（MCP 接入，2026-09-05）

- **症状**：用户担心 MCP 配置用的是旧安装模块，问是否要重装、是否要
  禁用再启用。
- **核实**：`.venv/lib/.../ _editable_impl_evolver.pth`——`uv sync` 默认
  可编辑安装，`evolver.__file__` 直指 `src/evolver/`；服务端线上回报
  1.112.0（含未提交工作树）。无需重装。
- **经验**：**Python stdio server 是长驻进程，代码在 spawn 时载入**。
  四条推论：(a) 工作区 MCP 配置在会话启动时加载——会话中途写入的配置
  本会话不可见，需新会话；(b) 改完引擎源码后必须重连 MCP 才加载新版；
  (c) **中间快照现象**——两次修复之间重连，进程会「半新半旧」（先修的
  生效、后修的缺席）；`ps -eo pid,lstart,command | grep mcp_server` 对比
  提交时刻可一锤定音；(d) 设置页重连只换进程，**已开会话的管道仍绑旧
  进程**——工具行为不变时须重启会话。验证模块新鲜度一行命令：
  `python -c "import evolver; print(evolver.__file__, evolver.__version__)"`。

### 17. 工具面缺两个：三层排查法（MCP 接入，2026-09-05）

- **症状**：客户端模型工具面 21/23，缺 `swarm_solidify` 与 `swarm_approvals`
  （两者无共性：一 destructive、一 read-only、schema 正常）。
- **排查**：(1) 配置层——`~/.zcode/cli/config.json` 与工作区配置均规范、
  无 enabled:false、无工具过滤字段；(2) 服务端层——直连 `tools/list`
  23 个全注册、schema/注解齐全；(3) 客户端组装层——无法从外部观测，
  但「destructive 注解被隐藏」假设被反例排除（三个 destructive 工具
  可见）。结论：长会话（1000+ 消息）中途接入的服务器被客户端工具面
  裁剪，裁谁近似随机。
- **经验**：**假阴性排查自底向上：证明每层干净再上移**，反例优先于假设
  （一个可见的 destructive 工具即推翻「注解过滤」论）。最终不可观测层
  用可执行的对照实验收口（新会话看是否 23/23）。缺的工具找 CLI 等价物
  （`evolver solidify` / `evolver hitl list`），不阻塞闭环。

### 18. asset_search 三重检索缺陷（MCP 工具体检，2026-09-05）

- **症状**：`tool_asset_search("hub retry")` 返回空——库里明明有
  `gene_hub_fetch_resilience` 等应命中基因；单关键词却正常。
- **根因（三面）**：(1) 整串子串匹配（`"hub retry" in haystack`）——多词
  查询需连续出现，必然落空；(2) `summary` 不在检索字段——而它是 Gene 的
  主文本（`penalize` 查不到 gene_applied_cooldown）；(3) `signals_match`
  不入检索（`hub_offline` 查空）。
- **修复**：token-AND 语义（分词后全命中才入选）+ `summary` 入 haystack +
  `signals_match` 列表拼接 + 结果 description 回退 summary；4 个新测试
  钉住（多词命中/多词带噪排除/summary 检索/signals 检索/空查询）。
- **经验**：**检索工具要用「真实查询语料」测，别只测单关键词**。用户自然
  输入是多词的；子串匹配对多词静默归零是最阴的假阴性。另：体检时
  proxy 路由同名函数是文件名搜索（不同域），勿误伤。

### 19. 重复固化无守卫（round-12，2026-09-07）

- **症状**：对已固化 run 再调 solidify，会烧完整级联（实测 424s）、以
  `ok:True` 结束且追加一条幻影 success 事件——验收门 soak 样本被无意义
  gated run 污染（verdict=ready 的输入!）。
- **修复**：`last_solidify.run_id == last_run.run_id` 时早退
  `already_solidified`（next_action=swarm_tick）；新 dispatch（新 run_id）
  永不受阻。
- **连锁**：守卫上线即被级联两次拒绝——`test_acceptance_shadow_lineage`
  的谱系链测试靠「同 run 固化两次」造事件链，与守卫冲突。按生产事实修
  测试：链跨 run 生成（每次 tick 新 run_id）。
- **经验**：**守卫落地时必须全文检索依赖旧行为的测试**——级联两次在同一
  位置拒绝，正是门在工作；「闪失」判断错了，位置取证（收集序 #204）才是正解。

### 20. 悬案：失败固化后状态文件消失（round-12，未定罪）

- **现象**：solidify 级联失败 → 回滚后 `evolution_solidify_state.json`
  消失（复现两次）。已排除：stash（文件被 gitignore 覆盖，`--include-
  untracked` 不触碰）、选择性删除（`--exclude-standard` 令其不可见）、
  tick（标记实验：状态过 tick 完好）。`record_landed_gene_ids` 会用空
  `last_run` 复活骨架状态（run_id 空 → 守卫跳过——这解释了守卫一度未触发）。
- **现状**：守卫封死危险路径（无级联→无回滚→无删除机会），实际影响已
  被压制；删除机制未定罪，标记实验复现脚本在 DEBUG 本条。
- **经验**：**未定罪的删除者要用「标记 + 全程验尸」实验圈定窗口**，而非
  源码遍历猜想——本轮源码三猜全错，实验一次定性 tick 无辜。

## 方法论沉淀

1. **覆盖审计先行**：`pytest --cov` 找冷分支再补测——#9 由审计钓出，非偶然。
2. **实证闭环**：每修必跑「根因场景」对照（设标志/造输入 → 修复前后行为差）；
   改了但没生效时，怀疑注入链上有 flag/噪音两层。
3. **静默降级是头号嫌疑**：skip/unvalidated/empty 且无指引的路径，六个 bug 里
   四个（#2/#6/#8/#10）生于静默。
4. **真仓即试验场**：dogfood 让 #1/#4/#5/#7 只可能在真实运行中现形——单测全绿
   不等于引擎能用。
5. **转达不是批准**：MCP 上的「人类」工具与申请者同一进程时，必须 fail-closed
   或切断（#12）。提示词政策挡不住无人值守。
6. **剧本 ≠ 落地**：选择器选出的基因 id 不是工作区里实际写下的基因 id（#13）。
   提交、冷却、创新日志必须同时记下两者。
7. **测试工具先于被测物**：「协议面过、数据面一刀切全挂」先查探针解包/断言
   （#14/#15）；写断言前先 raw dump 一次真实响应，别凭记忆写键名。
8. **长驻进程的重载语义**：stdio MCP server 只在 spawn 时载入代码——改码后
   重连才生效；会话中途加的配置要新会话才加载（#16）。
9. **三层排查**：配置层 → 服务端层 → 客户端组装层，逐层证明干净再上移；
   不可观测层用对照实验收口，缺的功能找 CLI 等价物绕行（#17）。
